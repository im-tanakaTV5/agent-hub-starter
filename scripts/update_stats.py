#!/usr/bin/env python3
import os
import json
from pathlib import Path

def get_stats():
    base_dir = Path(__file__).resolve().parent.parent
    
    # Agents count
    agents_dir = base_dir / 'agents'
    agent_count = 0
    if agents_dir.exists():
        agent_count = len(list(agents_dir.glob('*/CLAUDE.md')))
        
    # Departments count (unique prefixes like 01, 02)
    depts = set()
    if agents_dir.exists():
        for d in agents_dir.iterdir():
            if d.is_dir() and (d / 'CLAUDE.md').exists():
                prefix = d.name[:2]
                if prefix.isdigit():
                    depts.add(prefix)
    dept_count = len(depts)
    
    # Prompt character count
    char_count = 0
    prompt_files = []
    root_md = base_dir / 'CLAUDE.md'
    if root_md.exists():
        prompt_files.append(root_md)
    prompt_files.extend(sorted((base_dir / 'framework').glob('*.md')))
    if agents_dir.exists():
        prompt_files.extend(list(agents_dir.glob('*/CLAUDE.md')))
    shared_proto = base_dir / 'shared' / '共通プロトコル.md'
    if shared_proto.exists():
        prompt_files.append(shared_proto)
    user_prof = base_dir / 'shared' / 'profile' / 'ユーザープロファイル.md'
    if user_prof.exists():
        prompt_files.append(user_prof)
        
    for pf in prompt_files:
        try:
            char_count += len(pf.read_text(encoding='utf-8'))
        except:
            pass
            
    # Folders and Files count
    folder_count = 0
    file_count = 0
    for root, dirs, files in os.walk(base_dir):
        # Exclude hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        folder_count += len(dirs)
        file_count += len([f for f in files if not f.startswith('.')])
        
    stats = {
        "departments": dept_count,
        "agents": agent_count,
        "prompt_chars": char_count,
        "folders": folder_count,
        "files": file_count
    }
    
    out_file = base_dir / 'dashboard' / 'system_stats.json'
    out_file.parent.mkdir(exist_ok=True)
    out_file.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Updated stats: {stats}")

if __name__ == '__main__':
    get_stats()
