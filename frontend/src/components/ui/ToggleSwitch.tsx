/** 开关原语（TeamClaw settings/shared/ToggleSwitch 形态）：
 * 44×24 圆形滑块。开=交互蓝（绿保留给涨跌语义），关=轨道灰。 */
export function ToggleSwitch({ checked, onChange, disabled, title }: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`toggle-switch${checked ? " on" : ""}`}
      onClick={() => { if (!disabled) onChange(!checked); }}
      disabled={disabled}
      title={title}
    >
      <span className="toggle-thumb" />
    </button>
  );
}
