# deadhd 저장소 규칙

## 기능이 바뀌면 반드시 릴리즈한다

스킬의 동작이 바뀌는 변경(`feat`, `fix`, 그리고 `skills/deadhd` 아래의 렌더러·템플릿·SKILL.md 동작 변경)을 main 에 올릴 때는 같은 푸시에서 릴리즈까지 한다. README, 예시 그림, 데모 데이터만 바뀐 경우는 릴리즈하지 않는다.

1. `.claude-plugin/plugin.json` 의 `version` 을 올린다. `feat` 는 마이너, `fix` 는 패치, 기존 데이터나 설정과 호환이 깨지면 메이저를 올린다.
2. `chore: <바뀐 기능 요약> 버전 X.Y.Z` 로 커밋한다.
3. `vX.Y.Z` 주석 태그를 만들어 커밋과 함께 푸시한다.
4. 태그로 GitHub Release `vX.Y.Z` 를 만들고, 본문에 바뀐 기능과 업데이트 방법을 적는다.

플러그인 업데이트는 `version` 문자열로 판정된다. 버전을 올리지 않고 커밋만 푸시하면, 이미 설치한 사람은 `claude plugin update` 를 실행해도 "already at the latest version" 이 나오고 예전 파일을 계속 쓴다.

Orca 스킬 공유 링크는 게시할 때 올린 파일을 바꿀 수 없는 번들로 보관한다. 릴리즈해도 기존 링크의 내용은 바뀌지 않으므로, 링크를 새로 게시할지는 릴리즈할 때마다 따로 정한다.

## 테스트

```bash
python3 -m unittest skills/deadhd/test_render.py
```

테마 갤러리(`docs/themes.png`)는 `python3 docs/capture_themes.py` 로 다시 만든다.
