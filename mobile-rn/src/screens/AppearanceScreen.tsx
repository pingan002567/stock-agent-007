import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { SettingsGroup, SettingsNote, SettingsRow } from '../components/SettingsList';
import { useThemedStyles, useTokens } from '../lib/tokens';
import { useAppearance } from '../store/appearance';
import { ACCENT_PRESETS, useTheme } from '../store/theme';

export default function AppearanceScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const { accentHex, scheme, setAccent, setScheme } = useTheme();
  const backgroundUri = useAppearance((s) => s.backgroundUri);
  const dim = useAppearance((s) => s.dim);
  const [customHex, setCustomHex] = useState('');
  const [message, setMessage] = useState('');

  const flash = (m: string) => {
    setMessage(m);
    setTimeout(() => setMessage(''), 1800);
  };

  const applyCustomHex = () => {
    const v = customHex.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) {
      setAccent(v.toUpperCase());
      setCustomHex('');
      flash('已应用自定义主题色');
    } else {
      flash('请输入 #RRGGBB 格式');
    }
  };

  const pickWallpaper = async () => {
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.9 });
    if (res.canceled || !res.assets?.[0]) return;
    useAppearance.getState().setBackground(res.assets[0].uri);
    flash('背景已更新');
  };

  const dimPct = Math.round(dim * 100);

  return (
    <ScrollView style={[styles.container, { backgroundColor: t.pageBg }]} contentContainerStyle={styles.content}>
      <SettingsGroup title="主题颜色" footer={`当前 ${accentHex}，会作用于按钮、链接、选中态与 Tab 高亮。`}>
        <View style={styles.swatchWrap}>
          {ACCENT_PRESETS.map((p) => (
            <Pressable key={p.id} onPress={() => setAccent(p.hex)} style={styles.swatchItem}>
              <View style={[styles.swatch, { backgroundColor: p.hex }, accentHex === p.hex && styles.swatchOn]}>
                {accentHex === p.hex ? <Text style={styles.check}>✓</Text> : null}
              </View>
              <Text style={[styles.swatchLabel, { color: t.sub }]} numberOfLines={1}>
                {p.name}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={[styles.hexRow, { borderTopColor: t.sep }]}>
          <TextInput
            style={[styles.hexInput, { color: t.text, borderColor: t.sep }]}
            placeholder="#RRGGBB"
            placeholderTextColor={t.sub}
            value={customHex}
            onChangeText={setCustomHex}
            autoCapitalize="characters"
            autoCorrect={false}
          />
          <Pressable style={[styles.applyBtn, { backgroundColor: t.accent }]} onPress={applyCustomHex}>
            <Text style={styles.applyText}>应用</Text>
          </Pressable>
        </View>
      </SettingsGroup>

      <SettingsGroup title="显示模式">
        <View style={styles.segRow}>
          {(['system', 'light', 'dark'] as const).map((s) => {
            const on = scheme === s;
            return (
              <Pressable
                key={s}
                style={[styles.seg, { borderColor: on ? t.accent : t.sep, backgroundColor: on ? t.cardAlt : 'transparent' }]}
                onPress={() => setScheme(s)}
              >
                <Text style={[styles.segText, { color: on ? t.accent : t.sub }]}>
                  {s === 'system' ? '跟随系统' : s === 'light' ? '浅色' : '深色'}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </SettingsGroup>

      <SettingsGroup title="对话背景" footer="背景图仅保存在本机，不会上传。">
        <SettingsRow
          label={backgroundUri ? '更换背景图' : '选择背景图'}
          onPress={() => void pickWallpaper()}
        />
        {backgroundUri ? (
          <SettingsRow label="清除背景图" danger last onPress={() => useAppearance.getState().clearBackground()} />
        ) : (
          <SettingsNote>未设置背景图</SettingsNote>
        )}
      </SettingsGroup>

      {backgroundUri ? (
        <SettingsGroup title="遮罩浓度" footer="背景较亮时可提高遮罩，避免文字看不清。">
          <View style={styles.dimRow}>
            <Pressable style={[styles.dimBtn, { borderColor: t.sep }]} onPress={() => useAppearance.getState().setDim(dim - 0.05)}>
              <Text style={[styles.dimText, { color: t.text }]}>－</Text>
            </Pressable>
            <Text style={[styles.dimValue, { color: t.text }]}>{dimPct}%</Text>
            <Pressable style={[styles.dimBtn, { borderColor: t.sep }]} onPress={() => useAppearance.getState().setDim(dim + 0.05)}>
              <Text style={[styles.dimText, { color: t.text }]}>＋</Text>
            </Pressable>
          </View>
        </SettingsGroup>
      ) : null}

      {message ? <Text style={[styles.message, { color: t.accent }]}>{message}</Text> : null}
    </ScrollView>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1 },
  content: { paddingTop: 20, paddingBottom: 40 },
  swatchWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 14, padding: 16 },
  swatchItem: { alignItems: 'center', width: 60 },
  swatch: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  swatchOn: { borderWidth: 2, borderColor: '#111' },
  check: { color: '#fff', fontSize: 16, fontWeight: '700' },
  swatchLabel: { fontSize: 10.5, marginTop: 5 },
  hexRow: { flexDirection: 'row', gap: 8, paddingHorizontal: 16, paddingVertical: 12, borderTopWidth: StyleSheet.hairlineWidth },
  hexInput: { flex: 1, borderWidth: StyleSheet.hairlineWidth, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 14 },
  applyBtn: { borderRadius: 8, paddingHorizontal: 18, justifyContent: 'center' },
  applyText: { color: '#fff', fontWeight: '600', fontSize: 14 },
  segRow: { flexDirection: 'row', gap: 8, padding: 16 },
  seg: { flex: 1, borderWidth: 1, borderRadius: 9, paddingVertical: 9, alignItems: 'center' },
  segText: { fontSize: 13 },
  dimRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 20, paddingVertical: 16 },
  dimBtn: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 18, paddingVertical: 6 },
  dimText: { fontSize: 16 },
  dimValue: { fontSize: 15, minWidth: 52, textAlign: 'center' },
  message: { textAlign: 'center', fontSize: 13, marginTop: 4 },
});
