/**
 * Jenkins CI/CD Pipeline — eval-executor 容器（评测执行，SCF 事件函数镜像，Python）
 *
 * 服务范围: Executor 容器（executor/eval_executor，镜像 docker/executor/Dockerfile，构建上下文=仓库根）
 * 触发方式: 手动触发 / TGit Webhook（Multibranch，main/develop）
 *
 * 阶段:
 *   1. 环境准备 — Python3 + uv（与 eval 流水线共用 setup-python.sh）
 *   2. 代码静态检查 — ruff（非阻塞）+ mypy（非阻塞）
 *   3. 单元测试 — pytest（仅 tests/unit，阻塞）
 *   4. Docker 镜像构建与推送 → 腾讯云 CCR
 *
 * 镜像: ccr.ccs.tencentyun.com/sasan/agent-eval-executor
 *   - tag = ${branch}-${shortHash}-${BUILD_NUMBER}
 *   - main 分支额外推送 :latest
 *
 * 关键约定:
 *   - Python 阶段在 dir("executor") 内执行：executor/pyproject.toml 以 path 依赖复用 ../evaluator
 *     （[tool.uv.sources] agent-eval editable），须在 executor/ 目录下 uv sync 才能解析。
 *   - 集成测试（marker=integration，需真实 PG）不在 CI 执行；仅跑 tests/unit（阻塞）。
 *   - JUnit/HTML 产物落在 executor/report/，post 段路径带 executor/ 前缀。
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
        EXECUTOR_DIR = 'executor'
        DEPLOY_ENV   = "${env.BRANCH_NAME == 'main' ? 'production' : 'staging'}"
    }

    stages {

        // ============================================================
        //  Stage 1: 环境准备
        // ============================================================
        stage('环境准备') {
            steps {
                echo """========================================
Pipeline:    Agent Eval Executor
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
                dir("${EXECUTOR_DIR}") {
                    sh "uv sync --extra dev --default-index ${PYPI_MIRROR}"

                    // ---- ruff 检查 ----
                    script {
                        try {
                            sh '''
                                mkdir -p report
                                uv run ruff check eval_executor tests --output-format junit > report/ruff-results.xml
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
                                uv run mypy eval_executor --ignore-missing-imports --junit-xml report/mypy-results.xml
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
                    junit allowEmptyResults: true, testResults: "${EXECUTOR_DIR}/report/ruff-results.xml"
                    junit allowEmptyResults: true, testResults: "${EXECUTOR_DIR}/report/mypy-results.xml"
                }
            }
        }

        // ============================================================
        //  Stage 3: 单元测试（pytest — 阻塞）
        //  仅跑 tests/unit（集成测试需真实 PG，CI 不执行）
        // ============================================================
        stage('单元测试') {
            steps {
                dir("${EXECUTOR_DIR}") {
                    script {
                        try {
                            sh '''
                                mkdir -p report
                                uv run pytest tests/unit -v --tb=short --junitxml=report/test-results.xml
                            '''
                        } catch (Exception e) {
                            error("Executor - 单元测试失败: ${e.getMessage()}")
                        }
                    }
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: "${EXECUTOR_DIR}/report/test-results.xml"
                }
            }
        }

        // ============================================================
        //  Stage 4: Docker 镜像构建与推送
        //  构建上下文=仓库根（Dockerfile 内 COPY evaluator + executor）
        // ============================================================
        stage('Docker镜像构建与推送') {
            when {
                expression { currentBuild.currentResult != 'FAILURE' }
            }
            steps {
                script {
                    def dockerLib = load('cicd/scripts/docker-build.groovy')
                    dockerLib.buildAndPush('.', 'docker/executor/Dockerfile', 'agent-eval-executor')
                }
            }
        }
    }

    // ============================================================
    //  Post Actions
    // ============================================================
    post {
        success {
            echo 'Executor Pipeline 执行成功!'
        }
        failure {
            echo 'Executor Pipeline 执行失败，请检查日志!'
        }
        cleanup {
            cleanWs(notFailBuild: true, deleteDirs: true)
        }
    }
}
