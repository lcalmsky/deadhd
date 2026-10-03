# deadhd 저장소 규칙

## 기능이 바뀌면 반드시 릴리즈한다

스킬의 동작이 바뀌는 변경(`feat`, `fix`, 그리고 `skills/deadhd` 아래의 렌더러·템플릿·SKILL.md 동작 변경)을 main 에 올릴 때는 같은 푸시에서 릴리즈까지 한다. README, 예시 그림, 데모 데이터만 바뀐 경우는 릴리즈하지 않는다.

1. `.claude-plugin/plugin.json` 의 `version` 을 올린다. `feat` 는 마이너, `fix` 는 패치, 기존 데이터나 설정과 호환이 깨지면 메이저를 올린다.
2. `chore: <바뀐 기능 요약> 버전 X.Y.Z` 로 커밋한다.
3. `vX.Y.Z` 주석 태그를 만들어 커밋과 함께 푸시한다.
4. 태그로 GitHub Release `vX.Y.Z` 를 만들고, 본문에 바뀐 기능과 업데이트 방법을 적는다.
5. Orca 스킬 공유를 반드시 새로 게시하고, README 「Orca 에서 설치」 절의 링크와 「지금 링크에는 vX.Y.Z 가 들어 있고」 문구를 새 값으로 바꿔 푸시한다.
   - 게시 전에 `skills/deadhd` 에 커밋되지 않은 파일(`__pycache__` 포함)이 없는지 확인한다.
   - 게시는 Orca 가 실행 중인 이 컴퓨터에서 `orca skills share --skill <deadhd 의 Claude home ID> --bundle-name "deadhd vX.Y.Z" --json` 으로 한다. ID 는 `orca skills installed --json` 에서 찾는다. Orca 설정의 「에이전트와 Orca CLI 가 기술 링크를 게시하도록 허용」이 꺼져 있으면 사용자에게 앱에서 게시해 달라고 한다.
   - README 의 `<a id="orca-install"></a>` 앵커는 지우지 않는다. 외부 글이 `https://github.com/lcalmsky/deadhd#orca-install` 로 이 절을 가리킨다.

플러그인 업데이트는 `version` 문자열로 판정된다. 버전을 올리지 않고 커밋만 푸시하면, 이미 설치한 사람은 `claude plugin update` 를 실행해도 "already at the latest version" 이 나오고 예전 파일을 계속 쓴다.

Orca 스킬 공유 링크는 게시할 때 올린 파일을 바꿀 수 없는 번들로 보관하므로, 릴리즈마다 새로 게시해야 한다. 한 번 쓴 묶음 이름은 링크를 해제해도 다시 쓸 수 없고, 같은 이름으로 게시하면 마무리 단계에서 `skill-install-filesystem-failed` 로 실패한다. 그래서 묶음 이름에 버전을 붙인다. 묶음 이름이 달라도 설치되는 스킬 이름은 SKILL.md 의 `name` 인 `deadhd` 그대로다.

## 테스트

```bash
python3 -m unittest skills/deadhd/test_render.py
```

테마 갤러리(`docs/themes.png`)는 `python3 docs/capture_themes.py` 로 다시 만든다.
