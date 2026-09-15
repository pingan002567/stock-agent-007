import Foundation

struct SSEEvent: Sendable {
    let type: String
    let data: String
}

/// SSE over URLSessionDataDelegate so server-trust challenges hit TrustingURLSessionDelegate.
actor SSEClient {
    private let session: URLSession

    init(session: URLSession) {
        self.session = session
    }

    func stream(url: URL) -> AsyncThrowingStream<SSEEvent, Error> {
        AsyncThrowingStream { continuation in
            final class StreamBox: NSObject, URLSessionDataDelegate, @unchecked Sendable {
                let continuation: AsyncThrowingStream<SSEEvent, Error>.Continuation
                let trustDelegate: TrustingURLSessionDelegate
                var buffer = Data()
                var eventType = "message"
                var dataLines: [String] = []
                var session: URLSession?
                var task: URLSessionDataTask?

                init(
                    continuation: AsyncThrowingStream<SSEEvent, Error>.Continuation,
                    trustDelegate: TrustingURLSessionDelegate
                ) {
                    self.continuation = continuation
                    self.trustDelegate = trustDelegate
                }

                func start(url: URL) {
                    let config = URLSessionConfiguration.default
                    config.timeoutIntervalForRequest = 3600
                    config.timeoutIntervalForResource = 3600
                    config.requestCachePolicy = .reloadIgnoringLocalCacheData
                    let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
                    self.session = session
                    var request = URLRequest(url: url)
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    request.cachePolicy = .reloadIgnoringLocalCacheData
                    let task = session.dataTask(with: request)
                    self.task = task
                    task.resume()
                }

                func cancel() {
                    task?.cancel()
                    session?.invalidateAndCancel()
                }

                func urlSession(
                    _ session: URLSession,
                    didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
                ) {
                    trustDelegate.urlSession(session, didReceive: challenge, completionHandler: completionHandler)
                }

                func urlSession(
                    _ session: URLSession,
                    task: URLSessionTask,
                    didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
                ) {
                    trustDelegate.urlSession(session, task: task, didReceive: challenge, completionHandler: completionHandler)
                }

                func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
                    buffer.append(data)
                    while let range = buffer.range(of: Data("\n".utf8)) {
                        let lineData = buffer.subdata(in: buffer.startIndex..<range.lowerBound)
                        buffer.removeSubrange(buffer.startIndex..<range.upperBound)
                        let line = String(data: lineData, encoding: .utf8)?
                            .trimmingCharacters(in: CharacterSet(charactersIn: "\r")) ?? ""
                        handle(line: line)
                    }
                }

                func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
                    flushEvent()
                    if let error {
                        let ns = error as NSError
                        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled {
                            continuation.finish()
                        } else {
                            continuation.finish(throwing: TransportErrorMapper.map(error))
                        }
                    } else if let http = task.response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                        continuation.finish(throwing: APIError(message: "SSE HTTP \(http.statusCode)"))
                    } else {
                        continuation.finish()
                    }
                    session.finishTasksAndInvalidate()
                }

                private func handle(line: String) {
                    if line.hasPrefix(":") { return }
                    if line.isEmpty {
                        flushEvent()
                        return
                    }
                    if line.hasPrefix("event:") {
                        eventType = String(line.dropFirst(6)).trimmingCharacters(in: .whitespaces)
                    } else if line.hasPrefix("data:") {
                        dataLines.append(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces))
                    }
                }

                private func flushEvent() {
                    guard !dataLines.isEmpty else {
                        eventType = "message"
                        return
                    }
                    let data = dataLines.joined(separator: "\n")
                    continuation.yield(SSEEvent(type: eventType, data: data))
                    eventType = "message"
                    dataLines = []
                }
            }

            let trust = TrustingURLSessionDelegate()
            let box = StreamBox(continuation: continuation, trustDelegate: trust)
            continuation.onTermination = { _ in box.cancel() }
            box.start(url: url)
        }
    }
}
