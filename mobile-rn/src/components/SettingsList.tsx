import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Switch, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTokens } from '../lib/tokens';

type IoniconName = keyof typeof Ionicons.glyphMap;

/** 设置分组：小标题 + 白色圆角卡片 + 可选脚注 */
export function SettingsGroup({
  title,
  footer,
  children,
}: {
  title?: string;
  footer?: string;
  children: ReactNode;
}) {
  const t = useTokens();
  return (
    <View style={styles.group}>
      {title ? <Text style={[styles.groupTitle, { color: t.sub }]}>{title}</Text> : null}
      <View style={[styles.groupBody, { backgroundColor: t.groupBg }]}>{children}</View>
      {footer ? <Text style={[styles.footer, { color: t.sub }]}>{footer}</Text> : null}
    </View>
  );
}

/** 一行：图标 + 标签 + 右侧值/控件 + chevron（有 onPress 才可点） */
export function SettingsRow({
  icon,
  label,
  value,
  onPress,
  right,
  danger,
  last,
}: {
  icon?: IoniconName;
  label: string;
  value?: string;
  onPress?: () => void;
  right?: ReactNode;
  danger?: boolean;
  last?: boolean;
}) {
  const t = useTokens();
  const body = (
    <View
      style={[
        styles.row,
        !last && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.sep },
      ]}
    >
      {icon ? (
        <Ionicons
          name={icon}
          size={19}
          color={danger ? '#FF3B30' : t.sub}
          style={styles.icon}
        />
      ) : null}
      <Text style={[styles.label, { color: danger ? '#FF3B30' : t.text }]} numberOfLines={1}>
        {label}
      </Text>
      {value ? (
        <Text style={[styles.value, { color: t.sub }]} numberOfLines={1}>
          {value}
        </Text>
      ) : null}
      {right ?? null}
      {onPress ? <Ionicons name="chevron-forward" size={16} color="#C7C7CC" style={styles.chevron} /> : null}
    </View>
  );
  return onPress ? <Pressable onPress={onPress}>{body}</Pressable> : body;
}

/** 一行开关 */
export function SettingsSwitchRow({
  label,
  hint,
  value,
  onChange,
  disabled,
  last,
}: {
  label: string;
  hint?: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  last?: boolean;
}) {
  const t = useTokens();
  return (
    <View
      style={[
        styles.row,
        styles.switchRow,
        !last && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.sep },
      ]}
    >
      <View style={styles.switchText}>
        <Text style={[styles.label, { color: t.text }]}>{label}</Text>
        {hint ? <Text style={[styles.hint, { color: t.sub }]}>{hint}</Text> : null}
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        disabled={disabled}
        trackColor={{ true: t.accent }}
      />
    </View>
  );
}

/** 分组内的说明文字行 */
export function SettingsNote({ children }: { children: ReactNode }) {
  const t = useTokens();
  return (
    <View style={styles.row}>
      <Text style={[styles.note, { color: t.sub }]}>{children}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: 24 },
  groupTitle: { fontSize: 12.5, marginLeft: 30, marginBottom: 7, letterSpacing: 0.3 },
  groupBody: { marginHorizontal: 16, borderRadius: 12, overflow: 'hidden' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 48,
    paddingHorizontal: 16,
    gap: 10,
  },
  switchRow: { minHeight: 56, paddingVertical: 6 },
  icon: { width: 22, textAlign: 'center' },
  label: { flex: 1, fontSize: 15 },
  value: { fontSize: 14, maxWidth: '52%' },
  chevron: { marginLeft: 2 },
  switchText: { flex: 1, paddingRight: 12 },
  hint: { fontSize: 11.5, marginTop: 3, lineHeight: 16 },
  note: { flex: 1, fontSize: 12.5, lineHeight: 19, paddingVertical: 12 },
  footer: { fontSize: 11.5, marginTop: 7, marginHorizontal: 30, lineHeight: 16 },
});
