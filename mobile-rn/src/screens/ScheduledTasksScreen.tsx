import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { fetchScheduledTasks, runScheduledTaskNow, toggleScheduledTask } from '../api/client';
import { useConnection } from '../store/connection';
import type { ScheduledTask } from '../types';

export default function ScheduledTasksScreen() {
  const { baseURL, token } = useConnection();
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTasks(await fetchScheduledTasks(baseURL, token));
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (t: ScheduledTask) => {
    await toggleScheduledTask(baseURL, token, t.task_id, !t.enabled);
    await load();
  };

  const runNow = async (id: string) => {
    await runScheduledTaskNow(baseURL, token, id);
  };

  const renderItem = ({ item }: { item: ScheduledTask }) => (
    <View style={styles.row}>
      <View style={styles.main}>
        <Text style={styles.name}>{item.name}</Text>
        <Text style={styles.schedule}>{item.schedule}</Text>
        <Text style={styles.meta}>
          下次 {item.next_run_at ?? '—'}
          {item.last_status ? ` · 上次 ${item.last_status}` : ''}
        </Text>
        {item.last_error ? <Text style={styles.err}>{item.last_error}</Text> : null}
      </View>
      <Pressable onPress={() => void toggle(item)}>
        <Text style={styles.link}>{item.enabled ? '停用' : '启用'}</Text>
      </Pressable>
      <Pressable onPress={() => void runNow(item.task_id)} style={styles.runBtn}>
        <Text style={styles.runText}>立即执行</Text>
      </Pressable>
    </View>
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={tasks}
        keyExtractor={(t) => t.task_id}
        renderItem={renderItem}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
        ListEmptyComponent={loading ? <ActivityIndicator style={{ marginTop: 40 }} /> : <Text style={styles.muted}>暂无定时任务</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee' },
  main: { flex: 1 },
  name: { fontSize: 15, fontWeight: '600' },
  schedule: { fontSize: 12, color: '#666', marginTop: 2 },
  meta: { fontSize: 11, color: '#999', marginTop: 2 },
  err: { fontSize: 11, color: '#c0392b', marginTop: 2 },
  link: { color: '#007AFF', fontSize: 14, marginHorizontal: 12 },
  runBtn: { backgroundColor: '#eef4ff', borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6 },
  runText: { color: '#007AFF', fontSize: 12 },
  muted: { color: '#999', textAlign: 'center', marginTop: 40 },
});
