import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text } from 'react-native';
import { useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import { fetchReport } from '../api/client';
import { Markdown } from '../components/Markdown';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import type { ReportDetail } from '../types';

type Route = RouteProp<RootStackParamList, 'ReportDetail'>;

export default function ReportDetailScreen() {
  const route = useRoute<Route>();
  const { baseURL, token } = useConnection();
  const { reportId } = route.params;
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await fetchReport(baseURL, token, reportId));
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token, reportId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16 }}>
      <Text style={styles.title}>{report?.title ?? '报告'}</Text>
      {report?.conclusion ? (
        <Text style={styles.conclusion}>{report.conclusion}</Text>
      ) : null}
      {report?.content ? <Markdown text={report.content} /> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  title: { fontSize: 20, fontWeight: '700', marginBottom: 12 },
  conclusion: { fontSize: 14, color: '#444', lineHeight: 21, backgroundColor: '#f6f8fa', borderRadius: 8, padding: 12, marginBottom: 16 },
});
