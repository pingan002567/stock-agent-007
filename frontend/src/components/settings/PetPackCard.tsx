import { useEffect, useState } from "react";
import {
  BUILTIN_PACK,
  isDesktop,
  listCustomPacks,
  petPackRoot,
  revealPackDir,
  selectedPackId,
  setSelectedPackId,
  type CustomPackEntry,
} from "@/lib/petPackStore";
import { normalizePack } from "@/lib/petPack";
import { SectionCard } from "@/components/settings/SectionCard";

/** 桌宠外观：选择宠物包（内置 + 本地自定义）。
 *
 *  自定义包 = `~/.stockagent/pets/<名字>/` 下放 `pet.json` + 图集，
 *  改完刷新即生效，不需要重新编译（对齐 ChatGPT 宠物的做法）。
 */
export function PetPackCard() {
  const [selected, setSelected] = useState(selectedPackId);
  const [packs, setPacks] = useState<CustomPackEntry[]>([]);
  const [root, setRoot] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const desktop = isDesktop();

  /** 读目录 + 落状态；effect 里调用时不先 setState，避免同步 setState 触发级联渲染 */
  const load = async (): Promise<void> => {
    const [entries, dir] = await Promise.all([listCustomPacks(), petPackRoot()]);
    setPacks(entries);
    setRoot(dir);
    // 选中的包被删掉了 → 回退内置，否则设置里显示旧 id 但桌宠已经回退
    const ids = new Set([BUILTIN_PACK.pack.id, ...entries.map((e) => e.id)]);
    if (!ids.has(selectedPackId())) {
      setSelectedPackId(BUILTIN_PACK.pack.id);
      setSelected(BUILTIN_PACK.pack.id);
    }
  };

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        if (cancelled) return;
        await load();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const choose = (id: string) => {
    setSelected(id);
    setSelectedPackId(id);
  };

  /** 自定义包的显示名：解析失败就显示目录名 + 错误，不能静默当好的 */
  const describe = (entry: CustomPackEntry): { name: string; bad?: string } => {
    try {
      const pack = normalizePack(JSON.parse(entry.json));
      return { name: pack.displayName };
    } catch (err) {
      return { name: entry.id, bad: err instanceof Error ? err.message : String(err) };
    }
  };

  return (
    <SectionCard
      title="桌宠"
      description={
        desktop
          ? "选一只宠物陪你干活；自定义包放本地目录即生效"
          : "网页端只能用内置宠物；自定义包需要在桌面应用里使用"
      }
    >
      <div className="pet-pack-list">
        <button
          type="button"
          className={`pet-pack-item${selected === BUILTIN_PACK.pack.id ? " on" : ""}`}
          onClick={() => choose(BUILTIN_PACK.pack.id)}
        >
          <span className="pet-pack-name">{BUILTIN_PACK.pack.displayName}</span>
          <span className="pet-pack-meta">内置 · {BUILTIN_PACK.pack.description ?? ""}</span>
        </button>

        {packs.map((entry) => {
          const info = describe(entry);
          return (
            <button
              key={entry.id}
              type="button"
              className={`pet-pack-item${selected === entry.id ? " on" : ""}${info.bad ? " bad" : ""}`}
              onClick={() => choose(entry.id)}
              title={info.bad ?? entry.dir}
            >
              <span className="pet-pack-name">{info.name}</span>
              <span className="pet-pack-meta">
                {info.bad ? `包不合法：${info.bad}` : entry.id}
              </span>
            </button>
          );
        })}

        {packs.length === 0 && desktop ? (
          <p className="pet-pack-empty">
            还没有自定义宠物。把 <code>pet.json</code> 和 <code>atlas.webp</code> 放进下面这个目录，点「刷新」即可。
          </p>
        ) : null}
      </div>

      {desktop ? (
        <div className="pet-pack-actions">
          <button type="button" className="ghost-btn" onClick={() => void refresh()} disabled={loading}>
            {loading ? "刷新中…" : "刷新"}
          </button>
          <button
            type="button"
            className="ghost-btn"
            onClick={() => void (root ? revealPackDir(root) : Promise.resolve())}
            disabled={!root}
          >
            打开宠物目录
          </button>
          {root ? <span className="pet-pack-path">{root}</span> : null}
        </div>
      ) : null}

      {error ? <p className="pet-pack-error">{error}</p> : null}
    </SectionCard>
  );
}
