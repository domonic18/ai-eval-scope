import { Tree } from "antd";
import type { DirectoryManifest, DirectoryModule } from "../types";

interface DirectoryTreeProps {
  manifest: DirectoryManifest;
}

export default function DirectoryTree({ manifest }: DirectoryTreeProps) {
  const treeData = manifest.modules.map((mod: DirectoryModule) => ({
    title: `${mod.name} (${mod.file_count} 个文件)`,
    key: mod.path,
    children: mod.children.map((child) => ({
      title: child.path,
      key: `${mod.path}/${child.path}`,
      isLeaf: true,
    })),
  }));

  return (
    <div>
      <p>
        根目录: <strong>{manifest.root_dir}</strong>， 共 {manifest.total_files} 个文件，
        最大深度 {manifest.hierarchy_depth}
      </p>
      <Tree treeData={treeData} defaultExpandAll showLine />
    </div>
  );
}
