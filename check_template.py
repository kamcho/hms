
import re

def check_template_structure(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()

    stack = []
    # Regex for tags: {% tag ... %}
    # We care about: block, endblock, if, endif, for, endfor, with, endwith, while, endwhile (if supported, usu not in django), active_admission? no that's a var.
    # We need to capture the tag name.
    
    tag_re = re.compile(r'{%\s*(\w+)')
    
    # helper for end tags
    end_tags = {
        'endblock': 'block',
        'endif': 'if',
        'endfor': 'for',
        'endwith': 'with',
        'endfilter': 'filter',
        'endspaceless': 'spaceless',
        'endautoescape': 'autoescape',
        'endcomment': 'comment',
        # elif and else are intermediate
    }

    start_tags = set(end_tags.values())
    
    for i, line in enumerate(lines):
        # find all tags in the line
        matches = list(tag_re.finditer(line))
        
        for match in matches:
            tag_name = match.group(1)
            
            if tag_name in start_tags:
                stack.append((tag_name, i + 1))
                # print(f"Line {i+1}: Start {tag_name}")
            elif tag_name in end_tags:
                expected_start = end_tags[tag_name]
                if not stack:
                    print(f"Line {i+1}: Unexpected {tag_name}")
                    return
                
                last_tag, last_line = stack[-1]
                if last_tag == expected_start:
                    stack.pop()
                    # print(f"Line {i+1}: End {tag_name} (closes {last_tag} from {last_line})")
                else:
                    print(f"Line {i+1}: Mismatch! Found {tag_name}, expected closing for {last_tag} (from line {last_line})")
                    return
            elif tag_name in ['else', 'elif']:
                if not stack:
                    print(f"Line {i+1}: Unexpected {tag_name}")
                    return
                # Verify we are in an if or for (else can be in for)
                last_tag, last_line = stack[-1]
                if last_tag not in ['if', 'for', 'changed']: # Does 'changed' have else? No. 'for' has else. 'if' has else.
                     # Django forloop can have empty... wait empty is its own tag? 
                     # {% empty %} is valid in for.
                     pass
                if tag_name == 'elif' and last_tag != 'if':
                     print(f"Line {i+1}: elif tag inside {last_tag} block (from line {last_line})")
                     return

            elif tag_name == 'empty':
                 if not stack:
                    print(f"Line {i+1}: Unexpected {tag_name}")
                    return
                 last_tag, last_line = stack[-1]
                 if last_tag != 'for':
                      print(f"Line {i+1}: empty tag inside {last_tag} block (from line {last_line})")
                      return

    if stack:
        print("Unclosed blocks:")
        for tag, line in stack:
            print(f"  {tag} from line {line}")

check_template_structure('/home/kali/Downloads/hms/home/templates/home/patient_detail.html')
