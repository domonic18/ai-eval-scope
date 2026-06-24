/**
 * Jenkins CI/CD Pipeline — Agent Eval Web 容器（React 前端 + Express/Prisma 后端合并部署）
 *
 * 服务范围: Web 容器（web/frontend + web/backend，镜像 docker/web/Dockerfile 合并构建）
 * 触发方式: 手动触发 / TGit Webhook（Multibranch，main/develop）
 *
 * 阶段:
 *   1. 环境准备 — Node.js 20.11.0
 *   2. 前端代码静态检查 — ESLint（非阻塞）
 *   3. 前端构建验证 — tsc -b && vite build（阻塞）
 *   4. 后端代码静态检查 — ESLint（非阻塞）
 *   5. 后端类型检查 — tsc --noEmit（阻塞）
 *   6. 后端单元测试 — vitest（排除集成测试，阻塞）
 *   7. Docker 镜像构建与推送 → 腾讯云 CCR
 *
 * 镜像: ccr.ccs.tencentyun.com/sasan/agent-eval-web
 *   - tag = ${branch}-${shortHash}-${BUILD_NUMBER}
 *   - main 分支额外推送 :latest
 *
 * 后端单测说明：集成测试（*.integration.test.ts，依赖 postgres+minio）不在 CI 执行；
 *              仅跑纯单测（test:unit），失败阻塞。
 */

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    // ============================================================
    //  环境变量
    // ============================================================
    environment {
        NPM_MIRROR   = 'https://mirrors.cloud.tencent.com/npm/'
        FRONTEND_DIR = 'web/frontend'
        BACKEND_DIR  = 'web/backend'
        DEPLOY_ENV   = "${env.BRANCH_NAME == 'main' ? 'production' : 'staging'}"
    }

    stages {

        // ============================================================
        //  Stage 1: 环境准备
        // ============================================================
        stage('环境准备') {
            steps {
                echo """========================================
Pipeline:    Agent Eval Web
Branch:      ${env.BRANCH_NAME ?: 'N/A'}
Build:       ${env.BUILD_NUMBER}
Deploy Env:  ${env.DEPLOY_ENV}
========================================"""

                sh 'bash cicd/scripts/setup-nodejs.sh'
            }
        }

        // ============================================================
        //  Stage 2: 前端代码静态检查（ESLint — 非阻塞）
        // ============================================================
        stage('前端代码静态检查') {
            steps {
                dir("${FRONTEND_DIR}") {
                    sh 'npm ci'

                    script {
                        try {
                            sh 'npm run lint'
                        } catch (Exception e) {
                            echo "前端 ESLint 发现问题 (non-blocking): ${e.getMessage()}"
                            currentBuild.result = 'UNSTABLE'
                        }
                    }
                }
            }
        }

        // ============================================================
        //  Stage 3: 前端构建验证（tsc -b && vite build — 阻塞）
        // ============================================================
        stage('前端构建验证') {
            steps {
                dir("${FRONTEND_DIR}") {
                    script {
                        try {
                            sh 'npm run build'
                        } catch (Exception e) {
                            error("Web - 前端构建失败: ${e.getMessage()}")
                        }
                    }
                }
            }
        }

        // ============================================================
        //  Stage 4: 后端代码静态检查（ESLint — 非阻塞）
        // ============================================================
        stage('后端代码静态检查') {
            steps {
                dir("${BACKEND_DIR}") {
                    sh 'npm ci'

                    script {
                        try {
                            sh 'npm run lint'
                        } catch (Exception e) {
                            echo "后端 ESLint 发现问题 (non-blocking): ${e.getMessage()}"
                            currentBuild.result = 'UNSTABLE'
                        }
                    }
                }
            }
        }

        // ============================================================
        //  Stage 5: 后端类型检查（tsc --noEmit — 阻塞）
        // ============================================================
        stage('后端类型检查') {
            steps {
                dir("${BACKEND_DIR}") {
                    script {
                        try {
                            sh 'npm run typecheck'
                        } catch (Exception e) {
                            error("Web - 后端类型检查失败: ${e.getMessage()}")
                        }
                    }
                }
            }
        }

        // ============================================================
        //  Stage 6: 后端单元测试（vitest，排除集成测试 — 阻塞）
        // ============================================================
        stage('后端单元测试') {
            steps {
                dir("${BACKEND_DIR}") {
                    script {
                        try {
                            sh '''
                                mkdir -p report
                                npm run test:unit -- --reporter=junit --reporter=default --outputFile=report/test-results.xml
                            '''
                        } catch (Exception e) {
                            error("Web - 后端单元测试失败: ${e.getMessage()}")
                        }
                    }
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: "${BACKEND_DIR}/report/test-results.xml"
                }
            }
        }

        // ============================================================
        //  Stage 7: Docker 镜像构建与推送
        // ============================================================
        stage('Docker镜像构建与推送') {
            when {
                expression { currentBuild.currentResult != 'FAILURE' }
            }
            steps {
                script {
                    def dockerLib = load('cicd/scripts/docker-build.groovy')
                    dockerLib.buildAndPush('.', 'docker/web/Dockerfile', 'agent-eval-web', [])
                }
            }
        }
    }

    // ============================================================
    //  Post Actions
    // ============================================================
    post {
        success {
            echo 'Web Pipeline 执行成功!'
        }
        failure {
            echo 'Web Pipeline 执行失败，请检查日志!'
        }
        cleanup {
            cleanWs(notFailBuild: true, deleteDirs: true)
        }
    }
}
