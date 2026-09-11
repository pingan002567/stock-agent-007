import { describe, expect, it } from "vitest";
import { sessionUploadsFromHttp } from "@/api/copilot";
import {
  UPLOADS_UNSUPPORTED_COPY,
  attachmentsFromMessagePayload,
  isImageUploadFilename,
  modelSupportsVision,
} from "@/lib/sessionUploads";

describe("session upload helpers", () => {
  it("detects vision-capable session models the same way as DeerFlow config", () => {
    expect(modelSupportsVision("openai/gpt-4o")).toBe(true);
    expect(modelSupportsVision("anthropic/claude-sonnet-4")).toBe(true);
    expect(modelSupportsVision("dashscope/qwen-vl-max")).toBe(true);
    expect(modelSupportsVision("deepseek/deepseek-chat")).toBe(false);
    expect(modelSupportsVision(null)).toBe(false);
  });

  it("treats png/jpg/webp as images the agent may view", () => {
    expect(isImageUploadFilename("chart.PNG")).toBe(true);
    expect(isImageUploadFilename("shot.webp")).toBe(true);
    expect(isImageUploadFilename("report.pdf")).toBe(false);
    expect(isImageUploadFilename("notes")).toBe(false);
  });

  it("keeps the stub-runtime copy for the composer + button", () => {
    expect(UPLOADS_UNSUPPORTED_COPY).toContain("不支持读附件");
  });

  it("treats a missing GET /uploads route as an empty list, not a hard error", () => {
    expect(sessionUploadsFromHttp(404, null)).toEqual({
      supported: true,
      files: [],
      count: 0,
    });
  });

  it("reads attachment filenames from a persisted user message payload", () => {
    expect(
      attachmentsFromMessagePayload({
        attachments: [{ filename: "年报.pdf", size: 12, markdown_file: "年报.md" }],
      }),
    ).toEqual([{ filename: "年报.pdf", size: 12, markdown_file: "年报.md" }]);
    expect(attachmentsFromMessagePayload({})).toEqual([]);
  });
});
