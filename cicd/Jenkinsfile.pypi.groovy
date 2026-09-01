/**
 * Jenkins Pipeline — ai-eval-scope Python 包构建 / 校验 / 发布（docs/arch/17 §5）
 *
 * 服务范围: 评估器 evaluator/ → PyPI（或 TestPyPI 演练）
 * 触发方式: tag 推送（TAG_NAME）或手动带参（TAG）；无 tag 时退化为「构建演练」（只验不发）
 *
 * 与 Jenkinsfile.eval.groovy 的分工:
 *   - eval 流水线守 PR/分支质量（每次提交）
 *   - 本流水线守制品（tag 触发：质量门禁 → 构建 → 版本断言 + 冒烟 → 发布）
 *
 * 凭证: Jenkins Credentials `pypi-upload-token`（Secret text，PyPI project-scoped
 *        API token，见 arch/17 §8 P2）→ 注入 UV_PUBLISH_TOKEN。
 *        PyPI Trusted Publishing（OIDC）仅 GitHub Actions 可用，Jenkins 走 API token
 *        是行业标准做法。
 *
 * 流水线阶段:
 *   1. 环境准备 — 安装 Python3 + uv
 *   2. 质量门禁 — ruff + mypy（非阻塞）+ pytest 全量（阻塞）
 *   3. 构建     — uv build（sdist + wheel）
 *   4. 校验     — tag == 包版本断言（防错发）+ 双产物隔离冒烟
 *   5. 发布     — 仅 tag（v*）：uv publish（TEST_PYPI=true 走 TestPyPI）
 */

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 20, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    parameters {
        string(
            name: 'TAG', defaultValue: '',
            description: '发布 tag（如 v0.2.0；留空则只构建校验不发布）'
        )
        booleanParam(
            name: 'TEST_PYPI', defaultValue: false,
            description: '演练模式：发布到 test.pypi.org（正式发布前必演练一次）'
        )
    }

    // ============================================================
    //  环境变量（所有阶段共享）
    // ============================================================
    environment {
        // 国内镜像（仅 sync 走镜像；publish 直连官方 upload 端点）
        PYPI_MIRROR  = 'https://mirrors.cloud.tencent.com/pypi/simple'
        PYPI_HOST    = 'mirrors.cloud.tencent.com'
        // 发布 tag：tag 触发取 TAG_NAME，手动触发取参数 TAG
        RELEASE_TAG  = "${env.TAG_NAME ?: params.TAG ?: ''}"
    }

    stages {

        // ============================================================
        //  Stage 1: Setup — 安装/验证 Python3 + uv
        // ============================================================
        stage('环境准备') {
            steps {
                echo """========================================
Pipeline:    PyPI Publish (ai-eval-scope)
Release Tag: ${env.RELEASE_TAG ?: '（无 — 构建演练，只验不发）'}
Build:       ${env.BUILD_NUMBER}
========================================"""

                sh 'bash cicd/scripts/setup-python.sh'
            }
        }

        // ============================================================
        //  Stage 2: 质量门禁（与 eval 流水线同款：ruff + mypy 非阻塞，pytest 阻塞）
        // ============================================================
        stage('质量门禁') {
            steps {
                dir('evaluator') {
                    sh 'uv sync --group dev --default-index ${PYPI_MIRROR}'

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

                    sh '''
                        mkdir -p report
                        uv run pytest tests/ -v --tb=short \
                            --junitxml=report/test-results.xml \
                            --cov=agent_eval \
                            --cov-report=term-missing
                    '''
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'evaluator/report/*.xml'
                }
            }
        }

        // ============================================================
        //  Stage 3: 构建 — sdist + wheel 双产物（dist/）
        // ============================================================
        stage('构建') {
            steps {
                dir('evaluator') { sh 'uv build' }
            }
        }

        // ============================================================
        //  Stage 4: 校验 — 版本一致性断言 + 双产物隔离冒烟（uv 官方发布范式）
        // ============================================================
        stage('校验') {
            steps {
                dir('evaluator') {
                    sh '''#!/bin/bash
                        set -euo pipefail
                        # 防错发核心：发布 tag 必须等于包 __version__（cz bump 保证同步，此处兜底）
                        if [ -n "${RELEASE_TAG}" ]; then
                            VER="$(uv run python -c "import agent_eval; print(agent_eval.__version__)")"
                            if [ "v${VER}" != "${RELEASE_TAG}" ]; then
                                echo "版本不一致：tag(${RELEASE_TAG}) != 包版本(${VER})，禁止错发"
                                exit 1
                            fi
                            echo "版本一致：tag(${RELEASE_TAG}) == __version__(${VER})"
                        else
                            echo "无发布 tag（构建演练），跳过版本断言"
                        fi
                        # 冒烟即验收：wheel 与 sdist 各自在隔离环境安装并执行 CLI
                        # --refresh：防 agent 缓存里同版本旧 wheel 导致假通过（本地重演练时尤甚）
                        uv run --isolated --no-project --refresh --with dist/*.whl    agent-eval --version
                        uv run --isolated --no-project --refresh --with dist/*.tar.gz agent-eval --version
                    '''
                }
            }
        }

        // ============================================================
        //  Stage 5: 发布 — 仅 tag（v*）触发；TEST_PYPI=true 走演练通道
        //  PyPI 同版本号不可重传：发布失败修复合后必须 bump 版本（arch/17 §4）
        // ============================================================
        stage('发布') {
            when {
                expression { env.RELEASE_TAG ==~ /v\d.*/ }
            }
            steps {
                dir('evaluator') {
                    withCredentials([string(credentialsId: 'pypi-upload-token', variable: 'UV_PUBLISH_TOKEN')]) {
                        script {
                            if (params.TEST_PYPI) {
                                echo '演练模式：发布到 TestPyPI'
                                sh 'uv publish --publish-url https://test.pypi.org/legacy/'
                            } else {
                                echo "正式发布：${env.RELEASE_TAG} → PyPI"
                                sh 'uv publish'
                            }
                        }
                    }
                }
            }
        }
    }

    // ============================================================
    //  Post Actions
    // ============================================================
    post {
        always {
            // 归档构建产物（发布失败时留证排查）
            archiveArtifacts artifacts: 'evaluator/dist/*', allowEmptyArchive: true, fingerprint: true
        }
        success {
            echo 'ai-eval-scope 发布流水线执行成功!'
        }
        failure {
            echo 'ai-eval-scope 发布流水线执行失败，请检查日志!'
        }
        cleanup {
            cleanWs(notFailBuild: true, deleteDirs: true)
        }
    }
}
