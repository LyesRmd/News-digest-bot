#!/usr/bin/env bash
# يحفظ الحالة في فرع "state" بنسخة واحدة دائماً (force push) كي لا يتضخم المستودع
set -eu
cd state
rm -rf .git
git init -q -b state
git config user.name "news-bot"
git config user.email "news-bot@users.noreply.github.com"
git add -A
git commit -q --allow-empty -m "state $(date -u +%FT%TZ)"
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
git push -q -f origin state
