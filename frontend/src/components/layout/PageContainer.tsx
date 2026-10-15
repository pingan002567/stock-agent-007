/** 三栏布局后页面不再有独立 topbar（时钟/状态在左栏品牌区，搜索已移除），
 * 仅保留内容容器。 */
export function PageContainer({ children }: { children: React.ReactNode }) {
  return (
    <section className="content">
      {children}
    </section>
  );
}
