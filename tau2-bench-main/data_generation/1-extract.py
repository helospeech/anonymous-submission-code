import os
import re
import json

EXTRACTED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted")
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset.json")

def normalize_title(title):
    # Remove leading/trailing whitespace
    title = title.strip()
    # Remove leading numbers, dots, and asterisks (e.g. "1 草原" -> "草原", "* 红楼春趣" -> "红楼春趣")
    title = re.sub(r'^[\d\s\.\*]+', '', title)
    return title

def parse_textbook(file_path):
    lessons = {}
    current_title = None
    current_content = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                if current_title:
                    current_content.append(line)
                continue
            
            # Check for Lesson Header (### Title)
            # In textbooks, lessons start with ###
            match = re.match(r'^###\s+(.*)$', line)
            if match:
                # Save previous lesson
                if current_title:
                    lessons[current_title] = "\n".join(current_content).strip()
                
                # Start new lesson
                raw_title = match.group(1)
                current_title = normalize_title(raw_title)
                current_content = []
            else:
                if current_title:
                    current_content.append(line)
    
    # Save last lesson
    if current_title:
        lessons[current_title] = "\n".join(current_content).strip()
        
    return lessons

def parse_teacher_book(file_path):
    lessons = {}
    current_title = None
    current_section = None
    
    # Temp storage for current lesson
    lesson_data = {
        "analysis": [],
        "objectives": [],
        "suggestions": []
    }
    
    # Section Keywords
    SECTION_MAP = {
        "教材解析": "analysis",
        "教学目标": "objectives",
        "教学建议": "suggestions"
    }
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line_stripped = line.strip()
            
            # 1. Check for Section Header
            # Regex to match: (### or **) then keyword then optional (**)
            section_match = re.match(r'^(?:###|\*\*)\s*(教材解析|教学目标|教学建议)(?:\s*\*\*)?$', line_stripped)
            if section_match:
                keyword = section_match.group(1)
                current_section = SECTION_MAP[keyword]
                continue

            # 2. Check for Lesson Header
            # Must start with # or ## or ###, followed by number and text
            # But NOT be a section header (already checked above)
            # Also exclude lines that are just "###" or "##"
            lesson_match = re.match(r'^(?:#+)\s*(\d+\s+.*|.*)$', line_stripped)
            
            # Refined Lesson Match:
            # We need to distinguish "## 1 草原" from random "## Some Subsection"
            # However, typically lessons have a number or are distinct names.
            # In our files: 
            # 六上: ## 1 草原
            # 五下: ### 1 古诗三首
            # We assume any header starting with # that is NOT a section keyword is a Lesson.
            # But wait, "###" followed by "Section" was caught above.
            
            is_lesson_header = False
            if lesson_match:
                # It starts with #. It wasn't a section header.
                # Check if it looks like a lesson title (usually has number)
                # Or if we are not in any lesson yet.
                # Let's assume all Lesson headers start with number e.g. "1 Title"
                # OR we accept all # headers as potential lessons if they are not sections.
                # But wait, "## 第一单元" in 五下课本.txt (actually 六上课本 had no unit headers, but let's be careful)
                # In 五下教师.txt read result: "1→---", "3→### 1 古诗三首"
                # In 六上教师.txt: "## 1 草原"
                # Let's try to match strict "Header Number Title" pattern first
                if re.match(r'^(?:#+)\s*\d+\s+.*', line_stripped):
                    is_lesson_header = True
                elif re.match(r'^(?:#+)\s*.*', line_stripped):
                    # Fallback: starts with # but no number.
                    # Could be "## 第一单元" (Unit header). We probably want to ignore Unit headers.
                    # How to distinguish "## 第一单元" from "## 草原"?
                    # If it contains "单元", ignore?
                    if "单元" in line_stripped:
                        is_lesson_header = False
                    else:
                        # Treat as lesson if unsure?
                        # Let's print/log if we find ambiguous headers?
                        # For now, let's assume valid lessons have numbers or we accept them.
                        is_lesson_header = True

            if is_lesson_header:
                # Save previous lesson
                if current_title:
                    lessons[current_title] = {
                        k: "\n".join(v).strip() for k, v in lesson_data.items()
                    }
                
                # Start new lesson
                raw_title = lesson_match.group(1)
                current_title = normalize_title(raw_title)
                current_section = None
                lesson_data = {
                    "analysis": [],
                    "objectives": [],
                    "suggestions": []
                }
                continue
            
            # 3. Content
            if current_title and current_section:
                lesson_data[current_section].append(line_stripped)

    # Save last lesson
    if current_title:
        lessons[current_title] = {
            k: "\n".join(v).strip() for k, v in lesson_data.items()
        }
        
    return lessons

def main():
    if not os.path.exists(EXTRACTED_DIR):
        print(f"Directory not found: {EXTRACTED_DIR}")
        return

    files = os.listdir(EXTRACTED_DIR)
    
    # Group files by prefix (e.g. "六上")
    # File names: "六上教师.txt", "六上课本.txt"
    prefixes = set()
    for f in files:
        if f.endswith("教师.txt"):
            prefixes.add(f.replace("教师.txt", ""))
        elif f.endswith("课本.txt"):
            prefixes.add(f.replace("课本.txt", ""))
            
    all_data = []
    
    for prefix in prefixes:
        teacher_file = os.path.join(EXTRACTED_DIR, f"{prefix}教师.txt")
        textbook_file = os.path.join(EXTRACTED_DIR, f"{prefix}课本.txt")
        
        teacher_data = {}
        textbook_data = {}
        
        if os.path.exists(teacher_file):
            print(f"Parsing Teacher Book: {teacher_file}")
            teacher_data = parse_teacher_book(teacher_file)
            
        if os.path.exists(textbook_file):
            print(f"Parsing Textbook: {textbook_file}")
            textbook_data = parse_textbook(textbook_file)
            
        # Merge
        # We want to iterate over all unique titles found
        all_titles = set(teacher_data.keys()) | set(textbook_data.keys())
        
        for title in all_titles:
            # Skip if title seems to be a Unit header or empty
            if not title: continue
            
            entry = {
                "title": title,
                "grade_semester": prefix,
                "textbook_content": textbook_data.get(title, ""),
                "analysis": teacher_data.get(title, {}).get("analysis", ""),
                "objectives": teacher_data.get(title, {}).get("objectives", ""),
                "suggestions": teacher_data.get(title, {}).get("suggestions", "")
            }
            
            # Only add if we have at least some content
            if entry["textbook_content"] or entry["analysis"] or entry["objectives"] or entry["suggestions"]:
                all_data.append(entry)

    # Sort by grade/semester and title (optional)
    # all_data.sort(key=lambda x: (x['grade_semester'], x['title']))
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully processed {len(all_data)} lessons. Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
