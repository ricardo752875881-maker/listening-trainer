#!/bin/bash
# 精听工坊端到端冒烟：真实转写导入 → 学习数据 → 标记 → 测验判分 → 掌握流转 → 级联删除
set -e
export PYTHONIOENCODING=utf-8
BASE=http://localhost:8000
ROOT="C:/工作目录/项目/听力练习工具"
TMP=$ROOT/.e2e_tmp
mkdir -p "$TMP"
cat > "$TMP/title.txt" <<'EOF'
E2E冒烟测试
EOF
cat > "$TMP/transcript.txt" <<'EOF'
Georgie 乔治
Hello and welcome to Real Easy English. In this podcast, we talk about a different topic each week in easy English. I am Georgie.

你好，欢迎收听真实简单英语。每周用简单的英语谈论一个不同的话题。我是乔治。

Neil 尼尔
And I am Neil. Today we are going to talk about family traditions.

我是尼尔。今天我们要聊聊家庭传统。
EOF

echo "== 1. 导入（真实转写，small 模型 cpu/int8）=="
JOB=$(curl -s -X POST "$BASE/api/import/start" -F "audio=@$ROOT/data/sample_tts.wav" -F "title=<$TMP/title.txt" -F "transcript=<$TMP/transcript.txt" | .venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['jobId'])")
echo "jobId=$JOB"
DONE=""
for i in $(seq 1 60); do
  sleep 3
  ST=$(curl -s "$BASE/api/import/jobs/$JOB")
  if echo "$ST" | grep -q '"stage":"done"'; then DONE="$ST"; echo "  done after $((i*3))s: $ST"; break; fi
  if echo "$ST" | grep -qE '"stage":"(error|cancelled)"'; then echo "IMPORT FAILED: $ST"; exit 1; fi
done
[ -z "$DONE" ] && { echo "TIMEOUT"; exit 1; }
echo "$DONE" | grep -q '"audioOnly":false' || { echo "STILL AUDIO-ONLY: $DONE"; exit 1; }

MID=$(echo "$DONE" | .venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['materialId'])")
echo "materialId=$MID"

echo "== 2. 学习数据（对齐质量 + 中文标题）=="
curl -s "$BASE/api/materials/$MID" > "$TMP/mat.json"
.venv/Scripts/python.exe - "$TMP/mat.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
print("  title:", d['material']['title'])
assert '冒烟' in d['material']['title'], "中文标题乱码!"
sents = d['sentences']
aligned = [s for s in sents if s['aligned']]
print(f"  sentences={len(sents)} aligned={len(aligned)} unaligned={len(sents)-len(aligned)}")
for s in aligned:
    print(f"    [{s['startSec']:6.2f}-{s['endSec']:6.2f}] words={len(s['words'])}  {s['text'][:55]}")
assert len(aligned) >= 4, "aligned too few!"
PY

echo "== 3. 标记：生词(带释义) + 没听懂 =="
SID1=$(.venv/Scripts/python.exe -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));print(d['sentences'][0]['id'])" "$TMP/mat.json")
SID2=$(.venv/Scripts/python.exe -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));print(d['sentences'][1]['id'])" "$TMP/mat.json")
cat > "$TMP/vocab.json" <<'EOF'
{"text":"podcast","wordStart":2,"wordEnd":2,"type":"word","meaning":"播客"}
EOF
curl -s -X POST "$BASE/api/materials/$MID/sentences/$SID2/vocab" -H "Content-Type: application/json" --data @"$TMP/vocab.json" > /dev/null
curl -s -X PUT "$BASE/api/materials/$MID/sentences/$SID1/not-understood" -H "Content-Type: application/json" -d '{"marked":true}' > /dev/null
curl -s "$BASE/api/review/items" | .venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin);print(f\"  review items={len(d)}\", [(i['type'],i['text'],i.get('meaning')) for i in d])"

echo "== 4. 测验：生成 → 恢复 → 满分提交 =="
Q=$(curl -s -X POST "$BASE/api/materials/$MID/quiz/generate" -H "Content-Type: application/json" -d '{"count":10}')
echo "  generate: ${Q:0:120}..."
QID=$(echo "$Q" | .venv/Scripts/python.exe -c "import sys,json;print(json.load(sys.stdin)['quizId'])")
curl -s "$BASE/api/quiz/$QID" | .venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin);print('  restore ok, items=',len(d['items']))"
.venv/Scripts/python.exe - "$TMP/mat.json" <<'PY' > "$TMP/quiz_payload.json"
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
sents = {s['id']: s['text'] for s in d['sentences'] if s['aligned']}
print(json.dumps({"items": [{"sentenceId": sid, "userInput": txt} for sid, txt in sents.items()]}))
PY
RESULT=$(curl -s -X POST "$BASE/api/materials/$MID/quiz/submit" -H "Content-Type: application/json" -d "{\"quizId\":\"$QID\",$(cat "$TMP/quiz_payload.json" | .venv/Scripts/python.exe -c "import sys,json;print(json.dumps({'items':json.load(sys.stdin)['items']})[1:-1])")}")
echo "$RESULT" | .venv/Scripts/python.exe -c "import sys,json;d=json.load(sys.stdin);print(f\"  score={d['score']} stage={d['material']['stage']} best={d['material']['bestScore']}\");assert d['score']>=90 and d['material']['stage']=='mastered'"

echo "== 5. 级联删除 =="
curl -s -X DELETE "$BASE/api/materials/$MID" > /dev/null
curl -s "$BASE/api/materials" | .venv/Scripts/python.exe -c "import sys,json;print('  materials:',json.load(sys.stdin))"
curl -s "$BASE/api/review/items" | .venv/Scripts/python.exe -c "import sys,json;print('  review items after delete:',json.load(sys.stdin))"
rm -rf "$TMP"
echo "== E2E ALL PASSED =="
