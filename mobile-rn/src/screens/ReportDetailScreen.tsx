import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text } from 'react-native';
import { useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import { fetchReport } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { Markdown } from '../components/Markdown';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import type { ReportDetail } from '../types';
import { useThemedStyles } from '../lib/tokens';

type Route = RouteProp<RootStackParamList, 'ReportDetail'>;

export default function ReportDetailScreen() {
  const styles = useThemedStyles(baseStyles);
  const route = useRoute<Route>();
  const { baseURL, token } = useConnection();
  const { reportId } = route.params;
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await fetchReport(baseURL, token, reportId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token, reportId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
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

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  title: { fontSize: 20, fontWeight: '700', marginBottom: 12 },
  conclusion: { fontSize: 14, color: '#444', lineHeight: 21, backgroundColor: '#f6f8fa', borderRadius: 8, padding: 12, marginBottom: 16 },
});
