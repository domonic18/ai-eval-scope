#!/usr/bin/env node
/**
 * Jenkins API 封装脚本
 * 跨平台：Windows / Linux / macOS
 * 零依赖：仅使用 Node.js 标准库
 *
 * 用法:
 *   node jenkins_api.mjs info <job-name> <build-number>
 *   node jenkins_api.mjs log  <job-name> <build-number>
 *   node jenkins_api.mjs latest <job-name>
 *
 * 环境变量:
 *   JENKINS_URL   - Jenkins 地址, 如 https://jenkins.example.com
 *   JENKINS_USER  - Jenkins 用户名
 *   JENKINS_TOKEN - Jenkins API Token
 */

import https from 'https';
import http from 'http';

const BASE_URL = (process.env.JENKINS_URL || '').replace(/\/$/, '');
const USER = process.env.JENKINS_USER || '';
const TOKEN = process.env.JENKINS_TOKEN || '';

function checkEnv() {
  if (!BASE_URL) {
    console.error('错误: 未设置 JENKINS_URL 环境变量');
    console.error('请在 .claude/settings.local.json 中配置:');
    console.error('  "env": { "JENKINS_URL": "https://jenkins.example.com" }');
    process.exit(1);
  }
  if (!USER || !TOKEN) {
    console.error('错误: 未设置 JENKINS_USER 或 JENKINS_TOKEN 环境变量');
    console.error('请在 .claude/settings.local.json 中配置:');
    console.error('  "env": { "JENKINS_USER": "your-user", "JENKINS_TOKEN": "your-token" }');
    process.exit(1);
  }
}

function request(path) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, BASE_URL);
    const client = url.protocol === 'https:' ? https : http;
    const auth = Buffer.from(`${USER}:${TOKEN}`).toString('base64');

    const req = client.request(
      url,
      {
        headers: {
          Authorization: `Basic ${auth}`,
        },
      },
      (res) => {
        let data = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          data += chunk;
        });
        res.on('end', () => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(data);
          } else {
            reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 200)}`));
          }
        });
      }
    );

    req.on('error', (err) => {
      reject(new Error(`请求失败: ${err.message}`));
    });

    req.setTimeout(30000, () => {
      req.destroy();
      reject(new Error('请求超时(30s)'));
    });

    req.end();
  });
}

function cmdInfo(job, build) {
  if (!job || !build) {
    console.error('用法: info <job-name> <build-number>');
    process.exit(1);
  }
  request(`/job/${encodeURIComponent(job)}/${build}/api/json`).then(console.log);
}

function cmdLog(job, build) {
  if (!job || !build) {
    console.error('用法: log <job-name> <build-number>');
    process.exit(1);
  }
  request(`/job/${encodeURIComponent(job)}/${build}/consoleText`).then(console.log);
}

function cmdLatest(job) {
  if (!job) {
    console.error('用法: latest <job-name>');
    process.exit(1);
  }
  request(`/job/${encodeURIComponent(job)}/api/json`)
    .then((data) => {
      const json = JSON.parse(data);
      const num = json.lastBuild?.number ?? json.lastCompletedBuild?.number ?? '';
      console.log(num);
    })
    .catch((err) => {
      console.error('获取最新构建号失败:', err.message);
      process.exit(1);
    });
}

function cmdTestReport(job, build) {
  if (!job || !build) {
    console.error('用法: test-report <job-name> <build-number>');
    process.exit(1);
  }
  request(`/job/${encodeURIComponent(job)}/${build}/testReport/api/json`).then(console.log);
}

function main() {
  checkEnv();
  const [cmd, ...args] = process.argv.slice(2);

  switch (cmd) {
    case 'info':
      cmdInfo(args[0], args[1]);
      break;
    case 'log':
      cmdLog(args[0], args[1]);
      break;
    case 'latest':
      cmdLatest(args[0]);
      break;
    case 'test-report':
      cmdTestReport(args[0], args[1]);
      break;
    default:
      console.error('Jenkins API 工具');
      console.error('');
      console.error('用法:');
      console.error('  node jenkins_api.mjs info       <job-name> <build-number>  获取构建元数据');
      console.error('  node jenkins_api.mjs log        <job-name> <build-number>  获取构建日志');
      console.error('  node jenkins_api.mjs test-report <job-name> <build-number> 获取测试报告');
      console.error('  node jenkins_api.mjs latest     <job-name>                 获取最新构建号');
      console.error('');
      console.error('环境变量: JENKINS_URL, JENKINS_USER, JENKINS_TOKEN');
      process.exit(1);
  }
}

main();
