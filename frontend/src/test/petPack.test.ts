import { describe, expect, it } from "vitest";
import { frameInterval, normalizePack } from "@/lib/petPack";

const valid = {
  id: "demo",
  displayName: "示例",
  cell: 396,
  spritesheet: "atlas.webp",
  animations: {
    idle: { row: 0, frames: 6, fps: 4 },
    walk: { row: 1, frames: 8, fps: 15 },
  },
};

describe("宠物包校验", () => {
  it("合法包原样通过，并补齐 stage/rows/cols", () => {
    const pack = normalizePack(valid);
    expect(pack.stage).toBe(132);
    expect(pack.cols).toBe(8); // 取最大 frames
    expect(pack.rows).toBe(2); // 取最大 row + 1
    expect(pack.displayName).toBe("示例");
  });

  it("缺少必需动作时报错，且错误信息能定位到动作名", () => {
    const rest = { walk: valid.animations.walk };
    expect(() => normalizePack({ ...valid, animations: rest })).toThrow(/idle/);
  });

  it("行号超出 rows 时报错（做宠物的人最容易写错的地方）", () => {
    expect(() =>
      normalizePack({ ...valid, rows: 2, animations: { ...valid.animations, walk: { row: 5, frames: 8, fps: 15 } } }),
    ).toThrow(/超出 rows/);
  });

  it("帧数超出 cols 时报错", () => {
    expect(() =>
      normalizePack({ ...valid, cols: 4, animations: { ...valid.animations, walk: { row: 1, frames: 8, fps: 15 } } }),
    ).toThrow(/超出 cols/);
  });

  it("cell 超出范围时报错", () => {
    expect(() => normalizePack({ ...valid, cell: 8 })).toThrow(/cell/);
    expect(() => normalizePack({ ...valid, cell: 4096 })).toThrow(/cell/);
  });

  it("fps=0 表示静态帧，frameInterval 返回 0", () => {
    const pack = normalizePack({ ...valid, animations: { idle: { row: 0, frames: 1, fps: 0 }, walk: valid.animations.walk } });
    expect(frameInterval(pack.animations.idle)).toBe(0);
    expect(frameInterval(pack.animations.walk)).toBeCloseTo(1000 / 15, 5);
  });
});
