import "@testing-library/jest-dom";

/** Node 22+ 可能暴露不完整的 localStorage（--localstorage-file 未配置），盖住 jsdom。 */
class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  clear() {
    this.data.clear();
  }
  getItem(key: string) {
    return this.data.has(key) ? this.data.get(key)! : null;
  }
  key(index: number) {
    return [...this.data.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
  setItem(key: string, value: string) {
    this.data.set(String(key), String(value));
  }
}

const memory = new MemoryStorage();
try {
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: memory });
} catch {
  /* ignore */
}
try {
  Object.defineProperty(window, "localStorage", { configurable: true, value: memory });
} catch {
  /* ignore */
}
