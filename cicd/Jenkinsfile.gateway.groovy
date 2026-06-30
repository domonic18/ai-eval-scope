/**
 * Jenkins CI/CD Pipeline — eval-gateway 容器（第三方系统对接评估接入服务，Python/FastAPI）
 *
 * 服务范围: Gateway 容器（gateway/eval_gateway，镜像 docker/gateway/Dockerfile，构建上下文=仓库根）
 * 触发方式: 手动触发 / TGit Webhook（Multibranch，main/develop）
 *
 * 阶段:
 *   1. 环境准备 — Python3 + uv（与 eval 流水线共用 setup-python.sh）
 *   2. 代码静态检查 — ruff（非阻塞）+ mypy（非阻塞）
 *   3. 单元测试 — pytest（仅 tests/unit，阻塞）
 *   4. Docker 镜像构建与推送 → 腾讯云 CCR
 *
 * 镜像: ccr.ccs.tencentyun.com/sasan/agent-eval-gateway
 *   - tag = ${branch}-${shortHash}-${BUILD_NUMBER}
 *   - main 分支额外推送 :latest
 *
 * 关键约定:
 *   - Python 阶段在 dir("gateway") 内执行：gateway/pyproject.toml 以 path 依赖复用 ../evaluator
 *     （[tool.uv.sources] agent-eval editable），须在 gateway/ 目录下 uv sync 才能解析。
 *   - 集成测试（marker=integration，需真实 PG）不在 CI 执行；仅跑 tests/unit（阻塞）。
 *   - JUnit/HTML 产物落在 gateway/report/，post 段路径带 gateway/ 前缀（参照 web 流水线 ${BACKEND_DIR}/report）。
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
        PYPI_MIRROR  = 'https://mirrors.cloud.tencent.com/pypi/simple'
        PYPI_HOST    = 'mirrors.cloud.tencent.com'
        GATEWAY_DIR  = 'gateway'
        DEPLOY_ENV   = "${env.BRANCH_NAME == 'main' ? 'production' : 'staging'}"
    }

    stages {

        // ============================================================
        //  Stage 1: 环境准备
        // ============================================================
        stage('环境准备') {
            steps {
                echo """========================================
Pipeline:    Agent Eval Gateway
Branch:      ${env.BRANCH_NAME ?: 'N/A'}
Build:       ${env.BUILD_NUMBER}
Deploy Env:  ${env.DEPLOY_ENV}
========================================"""

                sh 'bash cicd/scripts/setup-python.sh'
            }
        }

        // ============================================================
        //  Stage 2: 代码静态检查（ruff + mypy — 非阻塞）
        // ============================================================
        stage('代码静态检查') {
            steps {
                dir("${GATEWAY_DIR}") {
                    sh "uv sync --extra dev --default-index ${PYPI_MIRROR}"

                    // ---- ruff 检查 ----
                    script {
                        try {
                            sh '''
                                mkdir -p report
                                uv run ruff check eval_gateway tests --output-format junit > report/ruff-results.xml
                            '''
                        } catch (Exception e) {
                            echo "Ruff check found issues (non-blocking): ${e.getMessage()}"
                            currentBuild.result = 'UNSTABLE'
                        }
                    }

                    // ---- mypy 类型检查 ----
                    script {
                        try {
                            sh '''
                                mkdir -p report
                                uv run mypy eval_gateway --ignore-missing-imports --junit-xml report/mypy-results.xml
                            '''
                        } catch (Exception e) {
                            echo "MyPy check found issues (non-blocking): ${e.getMessage()}"
                            currentBuild.result = 'UNSTABLE'
                        }
                    }
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: "${GATEWAY_DIR}/report/ruff-results.xml"
                    junit allowEmptyResults: true, testResults: "${GATEWAY_DIR}/report/mypy-results.xml"
                }
            }
        }

        // ============================================================
        //  Stage 3: 单元测试（pytest — 阻塞）
        //  仅跑 tests/unit（集成测试需真实 PG，CI 不执行）
        // ============================================================
        stage('单元测试') {
            steps {
                dir("${GATEWAY_DIR}") {
                    script {
                        try {
                            sh '''
                                mkdir -p report
                                uv run pytest tests/unit -v --tb=short --junitxml=report/test-results.xml
                            '''
                        } catch (Exception e) {
                            error("Gateway - 单元测试失败: ${e.getMessage()}")
                        }
                    }
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: "${GATEWAY_DIR}/report/test-results.xml"
                }
            }
        }

        // ============================================================
        //  Stage 4: Docker 镜像构建与推送
        //  构建上下文=仓库根（Dockerfile 内 COPY evaluator + gateway）
        // ============================================================
        stage('Docker镜像构建与推送') {
            when {
                expression { currentBuild.currentResult != 'FAILURE' }
            }
            steps {
                script {
                    def dockerLib = load('cicd/scripts/docker-build.groovy')
                    dockerLib.buildAndPush('.', 'docker/gateway/Dockerfile', 'agent-eval-gateway')
                }
            }
        }
    }

    // ============================================================
    //  Post Actions
    // ============================================================
    post {
        success {
            echo 'Gateway Pipeline 执行成功!'
        }
        failure {
            echo 'Gateway Pipeline 执行失败，请检查日志!'
        }
        cleanup {
            cleanWs(notFailBuild: true, deleteDirs: true)
        }
    }
}
