/** 设置页的分组卡片（标题 + 说明 + 内容）。
 *
 *  单独成文件：`PetPackCard` 之类的子卡片也要用它，放在 Settings.tsx 里
 *  会形成 Settings ↔ 子卡片的循环 import。
 */
export function SectionCard({ title, subtitle, description, icon, children }: {
  title: string;
  subtitle?: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="setting-card">
      <div className="setting-card-head">
        {icon && <div className="setting-icon-box">{icon}</div>}
        <div className="setting-card-heading">
          <div className="setting-card-title">{title}</div>
          {description && <div className="setting-card-desc">{description}</div>}
        </div>
        {subtitle && <span className="setting-card-badge">{subtitle}</span>}
      </div>
      <div className="setting-card-body">{children}</div>
    </div>
  );
}
