/**
 * 给 @react-native/gradle-plugin 的 included build 加阿里云镜像。
 *
 * 背景：本机 Gradle 解析 plugins.gradle.org 失败（curl 能通、Gradle 不通），
 * 而 settings.gradle.kts 里的 pluginManagement 是硬编码的三个仓库，
 * 根工程的 init script 管不到 included build 的插件解析，只能改这份文件。
 *
 * node_modules 不入库，所以每次 npm install 后用这个脚本重放（package.json 里挂 postinstall）。
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const target = resolve('node_modules/@react-native/gradle-plugin/settings.gradle.kts');
if (!existsSync(target)) {
  console.log('[patch-gradle-mirror] 未找到 gradle-plugin，跳过');
  process.exit(0);
}

const MARK = '// aliyun-mirror-patch';
let src = readFileSync(target, 'utf8');
if (src.includes(MARK)) {
  console.log('[patch-gradle-mirror] 已打过补丁');
  process.exit(0);
}

// plugins.gradle.org 在本机 Gradle 里 HEAD 失败（curl 通、Gradle 不通），
// 所以把它替换成阿里云镜像，而不是追加在后面。
src = src.replace(
  /pluginManagement \{\s*repositories \{([\s\S]*?)\}\s*\}/,
  `pluginManagement {
  repositories {
    maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") } ${MARK}
    maven { url = uri("https://maven.aliyun.com/repository/google") }
    maven { url = uri("https://maven.aliyun.com/repository/public") }
    mavenCentral()
    google()
  }
}`,
);
if (!src.includes(MARK)) {
  console.log('[patch-gradle-mirror] 结构不匹配，未改动（升级 RN 后请检查）');
  process.exit(0);
}
writeFileSync(target, src);
console.log('[patch-gradle-mirror] 已为 gradle-plugin 加上阿里云镜像');
