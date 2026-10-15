import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView } from 'react-native';
import { useConnection } from './src/store/connection';
import ConnectScreen from './src/screens/ConnectScreen';
import ChatScreen from './src/screens/ChatScreen';

export default function App() {
  const status = useConnection((s) => s.status);
  const hydrate = useConnection((s) => s.hydrate);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <StatusBar style="auto" />
      {status === 'connected' ? <ChatScreen /> : <ConnectScreen />}
    </SafeAreaView>
  );
}
