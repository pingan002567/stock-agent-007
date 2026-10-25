/**
 * 打包安卓 release APK，并**只保留最新一份产物**。
 *
 * 以前每打一次就多一个 `StockAgent-0.2.x-arm64.apk`，堆了四五个几十兆的包。
 * 现在：构建 → 删掉旧的 StockAgent-*.apk → 用当前 versionName 命名放回。
 *
 * 用法：npm run package:android
 */

import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const gradleFile = join(root, 'android/app/build.gradle');
const apkOut = join(root, 'android/app/build/outputs/apk/release/app-release.apk');

const gradle = readFileSync(gradleFile, 'utf8');
const version = /versionName\s+"([^"]+)"/.exec(gradle)?.[1];
if (!version) {
  console.error('[package-android] 读不到 versionName');
  process.exit(1);
}

const javaHome = process.env.JAVA_HOME || '/opt/homebrew/opt/openjdk@17';
console.log(`[package-android] 打包 ${version}（arm64-v8a，JAVA_HOME=${javaHome}）`);

execFileSync(
  './gradlew',
  ['assembleRelease', '-PreactNativeArchitectures=arm64-v8a', '--console=plain'],
  { cwd: join(root, 'android'), stdio: 'inherit', env: { ...process.env, JAVA_HOME: javaHome } },
);

if (!existsSync(apkOut)) {
  console.error('[package-android] 构建成功但找不到产物');
  process.exit(1);
}

// 只留最新：删掉所有旧版本
const old = readdirSync(root).filter((f) => /^StockAgent-.*\.apk$/.test(f));
for (const f of old) {
  rmSync(join(root, f), { force: true });
  console.log(`[package-android] 已删除旧产物 ${f}`);
}

const target = join(root, `StockAgent-${version}-arm64.apk`);
copyFileSync(apkOut, target);
const mb = (statSync(target).size / 1024 / 1024).toFixed(1);
console.log(`[package-android] 产物：${target}（${mb} MB，仅保留这一份）`);
