import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { useConnection } from './src/store/connection';
import { useTheme } from './src/store/theme';
import ConnectScreen from './src/screens/ConnectScreen';
import { RootNavigator } from './src/navigation';

export default function App() {
  const status = useConnection((s) => s.status);
  const hydrate = useConnection((s) => s.hydrate);
  const hydrateTheme = useTheme((s) => s.hydrate);

  useEffect(() => {
    hydrate();
    hydrateTheme();
  }, [hydrate, hydrateTheme]);

  return (
    <>
      <StatusBar style="auto" />
      {status === 'connected' ? <RootNavigator /> : <ConnectScreen />}
    </>
  );
}
