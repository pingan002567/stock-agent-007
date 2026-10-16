import { registerRootComponent } from 'expo';

import App from './App';
// 必须在 App 启动前加载：defineTask 要求模块初始化时注册
import './src/lib/pushTask';

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);
