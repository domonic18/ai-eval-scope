/**
 * Jenkins CI/CD Pipeline — agent-eval-system
 *
 * 服务范围: 评估系统核心（Python 单体仓库）
 * 触发方式: Jenkins Multibranch Pipeline 自动触发 / 手动触发
 *
 * 设计原则:
 *   1. 公共安装脚本提取到 cicd/scripts/，共用
 *   2. 使用国内镜像源（腾讯云 PyPI）
 *   3. Setup 阶段与业务阶段分离，工具安装幂等
 *
 * 流水线阶段:
 *   1. 环境准备 — 安装 Python3 + uv
 *   2. 代码静态检查 — ruff（非阻塞）+ mypy（非阻塞）
 *   3. 单元测试 — pytest（阻塞，失败则中断）
 */

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    // ============================================================
    //  环境变量（所有阶段共享）
    // ============================================================
    environment {
        // 国内镜像
        PYPI_MIRROR  = 'https://mirrors.cloud.tencent.com/pypi/simple'
        PYPI_HOST    = 'mirrors.cloud.tencent.com'

        // 部署环境（master → production，其他 → staging）
        DEPLOY_ENV = "${env.BRANCH_NAME == 'master' ? 'production' : 'staging'}"
    }

    stages {

        // ============================================================
        //  Stage 1: Setup — 安装/验证 Python3 + uv
        // ============================================================
        stage('环境准备') {
            steps {
                echo """========================================
Pipeline:    Agent Eval
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
                sh 'uv sync --extra dev --default-index ${PYPI_MIRROR}'

                // ---- ruff 检查 ----
                script {
                    try {
                        sh '''
                            mkdir -p report
                            uv run ruff check agent_eval/ tests/ --output-format junit > report/ruff-results.xml
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
                            uv run mypy agent_eval/ --ignore-missing-imports --junit-xml report/mypy-results.xml
                        '''
                    } catch (Exception e) {
                        echo "MyPy check found issues (non-blocking): ${e.getMessage()}"
                        currentBuild.result = 'UNSTABLE'
                    }
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'report/ruff-results.xml'
                    junit allowEmptyResults: true, testResults: 'report/mypy-results.xml'
                }
            }
        }

        // ============================================================
        //  Stage 3: 单元测试（pytest — 阻塞）
        // ============================================================
        stage('单元测试') {
            steps {
                script {
                    try {
                        sh '''
                            mkdir -p report
                            uv run pytest tests/ -v --tb=short \
                                --junitxml=report/test-results.xml \
                                --cov=agent_eval \
                                --cov-report=term-missing \
                                --cov-report=html:report/htmlcov
                        '''
                    } catch (Exception e) {
                        error("pytest 测试失败: ${e.getMessage()}")
                    }
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'report/test-results.xml'
                    // 发布 HTML 覆盖率报告
                    publishHTML(target: [
                        allowMissing: true,
                        alwaysLinkToLastBuild: false,
                        keepAll: true,
                        reportDir: 'report/htmlcov',
                        reportFiles: 'index.html',
                        reportName: 'Coverage Report',
                        reportTitles: ''
                    ])
                }
            }
        }

        // ============================================================
        //  Stage 4: Docker 镜像构建与推送（暂不启用）
        //  后续需要部署时取消注释即可
        // ============================================================
        // stage('Docker镜像构建与推送') {
        //     when {
        //         expression { currentBuild.currentResult != 'FAILURE' }
        //     }
        //     steps {
        //         echo 'Docker 镜像构建与推送暂未启用'
        //         // 示例：使用 docker-build 共享脚本
        //         // script {
        //         //     def dockerLib = load('cicd/scripts/docker-build.groovy')
        //         //     dockerLib.buildAndPush('.', 'deploy/docker/Dockerfile', 'agent-eval')
        //         // }
        //     }
        // }
    }

    // ============================================================
    //  Post Actions
    // ============================================================
    post {
        success {
            echo 'Agent Eval Pipeline 执行成功!'
        }
        failure {
            echo 'Agent Eval Pipeline 执行失败，请检查日志!'
        }
        cleanup {
            cleanWs(notFailBuild: true, deleteDirs: true)
        }
    }
}
