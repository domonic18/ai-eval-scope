/**
 * Docker 镜像构建与推送共享脚本
 *
 * 用法（在 Jenkinsfile CD Stage 中）:
 *   script {
 *       def docker = load('cicd/scripts/docker-build.groovy')
 *       docker.buildAndPush('.', 'docker/web/Dockerfile', 'agent-eval-web')
 *   }
 *
 * 参数:
 *   serviceDir   — 构建上下文目录（仓库根用 '.'）
 *   dockerfile   — Dockerfile 相对路径（如 docker/web/Dockerfile）
 *   serviceName  — 镜像服务名（如 agent-eval-web）
 *   buildArgs    — 可选构建参数列表，每项为 [key, value]
 *
 * 设计要点:
 *   1. latest 标签仅在 main 分支推送，避免 feature 分支覆盖生产镜像
 *   2. push 带重试（3次），应对 registry 网络抖动
 *   3. 避免脚本级变量（Jenkins 沙箱不允许跨方法访问）
 */

/**
 * 带重试的 docker push
 */
def pushWithRetry(String imageTag) {
    int maxRetries = 3
    for (int i = 1; i <= maxRetries; i++) {
        try {
            sh "docker push ${imageTag}"
            return
        } catch (Exception e) {
            echo ">>> docker push 第 ${i}/${maxRetries} 次失败: ${e.getMessage()}"
            if (i == maxRetries) {
                error("docker push ${imageTag} 失败，已重试 ${maxRetries} 次")
            }
            sleep(5)
        }
    }
}

def buildAndPush(String serviceDir, String dockerfile, String serviceName, List buildArgs = []) {
    // ---- 1. 生成镜像标签 ----
    def shortHash = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
    def branch = (env.BRANCH_NAME ?: 'main').replace('/', '-')
    def tag = "${branch}-${shortHash}-${env.BUILD_NUMBER}"

    // ---- 2. 镜像名称 ----
    def imageName = "ccr.ccs.tencentyun.com/sasan/${serviceName}"
    def fullTag = "${imageName}:${tag}"
    def isMain = (env.BRANCH_NAME == 'main')

    echo ">>> 构建镜像: ${fullTag}"

    // ---- 3. 构建参数 ----
    def buildArgStr = ''
    for (def ba : buildArgs) {
        def key = ba.get(0)
        def val = ba.get(1)
        if (val) {
            buildArgStr += " --build-arg ${key}=${val}"
        }
    }

    // ---- 4. 构建镜像（从项目根目录）----
    docker.withRegistry('https://ccr.ccs.tencentyun.com', 'tencent-registry-credentials') {
        def latestTagOpt = isMain ? " -t ${imageName}:latest" : ''
        sh """
            docker build \
                --pull \
                -f ${dockerfile} \
                ${buildArgStr} \
                -t ${fullTag} \
                ${latestTagOpt} \
                ${serviceDir}
        """
    }

    // ---- 5. 推送到腾讯云 CCR ----
    docker.withRegistry('https://ccr.ccs.tencentyun.com', 'tencent-registry-credentials') {
        pushWithRetry(fullTag)
        if (isMain) {
            pushWithRetry("${imageName}:latest")
        }
    }

    echo ">>> 镜像已推送: ${fullTag}"

    // ---- 6. 设置环境变量供通知使用 ----
    env.IMAGE_NAME = imageName
    env.IMAGE_TAG = tag
}

return this
