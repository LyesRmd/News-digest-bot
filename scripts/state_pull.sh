#!/usr/bin/env bash
# يسترجع الحالة من فرع "state" (إن وُجد)
set -u
REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
rm -rf state
if git clone --quiet --depth=1 --branch state "$REPO_URL" state 2>/dev/null; then
  echo "تم استرجاع الحالة"
else
  mkdir -p state
  echo "لا حالة سابقة (أول تشغيل)"
fi
exit 0
