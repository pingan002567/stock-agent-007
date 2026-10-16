import { useEffect, useState, type ReactNode } from 'react';
import { Modal, Pressable, StyleSheet, View, type ViewStyle } from 'react-native';
import { useThemedStyles } from '../lib/tokens';

interface Props {
  visible: boolean;
  onClose: () => void;
  children: ReactNode;
  /** 弹层高度（默认自适应内容） */
  height?: ViewStyle['height'];
}

/**
 * 通用底部弹层：点击上方空白收起。
 * 遮罩与弹层是「兄弟节点」，所以点弹层内部（列表滚动/输入框/按钮）不会误触收起。
 * 另带 350ms 就绪窗口，避免打开它的那一次触摸穿透到遮罩、刚展开就被关掉。
 */
export function Sheet({ visible, onClose, children, height }: Props) {
  const styles = useThemedStyles(baseStyles);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!visible) {
      setReady(false);
      return;
    }
    const t = setTimeout(() => setReady(true), 350);
    return () => clearTimeout(t);
  }, [visible]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={() => ready && onClose()} />
        <View style={[styles.sheet, height ? { height } : null]}>{children}</View>
      </View>
    </Modal>
  );
}

const baseStyles = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  backdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  sheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingBottom: 28,
    paddingTop: 8,
  },
});
