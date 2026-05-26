import os
import glob
import re
import json

MD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "origin-data", "初高中教材-教师用书-markdown")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "dataset_extracted.json")

BLACKLIST = {
    "目录", "阅读", "写作", "综合性学习", "名著导读", "课外古诗词诵读",
    "预习", "思考探究", "积累拓展", "读读写写", "阅读提示", "写作实践",
    "学习提示", "学习活动", "学习任务", "单元说明", "教学指导", "课文解说",
    "单元教学设计举例", "资料链接", "整体把握", "问题探究", "素养提升",
    "教学建议", "作者简介", "参考答案", "练习说明", "编写说明", "关于教材",
    "关于教师教学用书", "教师教学用书", "义务教育教科书", "图书在版编目数据",
    "前言", "后记", "附录", "单元目标", "编写意图", "教学设计", "写作实践",
    "文从字顺", "怎样选材", "语言简明", "抓住细节", "学习抒情", "写出人物的精神",
    "课文研读", "一总体建议", "二教学设计", "三问题探究", "一整体把握", "二素养提升",
    "图书在版编目", "副词", "介词", "连词", "叹词和拟声词", "排比", "天下国家", 
    "说明", "任务", "家乡文化生活", "整本书阅读", "词语积累与词语解释", "古诗词诵读",
    "单元研习任务", "单元学习任务"
}

def clean_title(raw_title):
    # 去除开头的 # * 空格
    title = re.sub(r'^[\#\*\s]+', '', raw_title)
    
    # 去除开头的课文编号（加入对“、”的支持，修复“一、”截断问题）
    title = re.sub(r'^(?:第?[一二三四五六七八九十\d]+[\*＊]?[课单元]?[\.\s、]*)+', '', title)
    title = re.sub(r'^[\*＊]\s*\d+\s*', '', title)
    title = re.sub(r'^[\*＊]\s*', '', title)
    
    # 先去除节选标识
    title = re.sub(r'[\(（]节选[\)）]', '', title)
    
    # 统一清除所有标点符号（解决课本与教参标点不一致的问题）
    title = re.sub(r'[《》\?\!！？，。：:；、·\(\)（）“”‘’\'" \-——]', '', title)
    
    # 去除末尾的脚注、页码、字母等（加入 +$ 限制，避免误删《阿Q正传》等正常英文）
    title = re.sub(r'[①②③④a-zA-Z\d\s]+$', '', title)
    
    # 去除内部的所有空格
    title = title.replace(' ', '').replace(' ', '').replace('\t', '')
    
    # 针对某些特殊情况，如 "1沁园春长沙" 中的1可能没被完全去掉
    title = re.sub(r'^\d+', '', title)
    # 去除表格标签等HTML残留
    title = re.sub(r'<[^>]+>', '', title)
    
    return title.strip()

def parse_md_file(filepath):
    lessons = {}
    current_title = None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            stripped_line = line.strip()
            
            m = re.match(r'^#+\s+(.*)', line)
            if m:
                raw_t = m.group(1)
                t = clean_title(raw_t)
                
                # 过滤掉黑名单或太短/太长的无意义标题（长度限制放宽至 25）
                if t and t not in BLACKLIST and len(t) > 1 and len(t) <= 25:
                    current_title = t
                    if current_title not in lessons:
                        lessons[current_title] = []
                    # 累加内容，避免覆盖
                    lessons[current_title].append(stripped_line)
                else:
                    # 如果不是有效标题（比如命中了黑名单的“教学建议”），内容依然追加到上一篇课文
                    if current_title:
                        lessons[current_title].append(stripped_line)
            else:
                if current_title:
                    lessons[current_title].append(stripped_line)
                    
    # 将列表拼接成字符串
    return {k: "\n".join(v).strip() for k, v in lessons.items()}

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    dataset = []
    textbook_files = glob.glob(os.path.join(MD_DIR, "*课本.md"))
    total_lessons = 0
    
    for tb_file in textbook_files:
        basename = os.path.basename(tb_file).replace("课本.md", "")
        tc_file = os.path.join(MD_DIR, f"{basename}教参.md")
        
        if os.path.exists(tc_file):
            tb_lessons = parse_md_file(tb_file)
            tc_lessons = parse_md_file(tc_file)
            
            # 取交集
            common_titles = set(tb_lessons.keys()).intersection(set(tc_lessons.keys()))
            # 进一步过滤可能的杂音（比如正好交集里有 '一作者简介'）
            common_titles = {t for t in common_titles if not re.match(r'^[一二三四五六七八九十]、', t)}
            
            print(f"[{basename}] 提取了 {len(common_titles)} 篇课文: {', '.join(list(common_titles))}")
            total_lessons += len(common_titles)
            
            for title in common_titles:
                dataset.append({
                    "grade_semester": basename,
                    "lesson_title": title,
                    "textbook_content": tb_lessons[title], # 截取前2500字
                    "teacher_content": tc_lessons[title]
                })
            
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
        
    print(f"\n总计提取了 {total_lessons} 篇课文！已保存至 {OUT_FILE}")

if __name__ == "__main__":
    main()
