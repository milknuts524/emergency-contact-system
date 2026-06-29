# Emergency Contact System

Emergency Contact System は、利用者の安否・状態報告と、管理者による状況集約を目的とした軽量なWebアプリケーションです。

Python / FastAPI / SQLite / Jinja2 で構成され、macOS上では `start.command`、Windowsでは `start.bat` から起動できます。PWA、Web Push通知、CSV入出力、管理画面での設定変更に対応しています。

運用は自己責任でお願いします。

---

## システム要件

- macOS / Windows / Linux
- Python 3.11 以上
- FastAPI
- Uvicorn
- Cloudflare Tunnel を使う場合は `cloudflared`

Emergency Contact System 本体は Python / FastAPI / SQLite で構成されているため、macOS / Windows / Linux で動作可能です。

ただし、付属の簡単起動スクリプトはOSごとに異なります。

- macOS: `start.command`
- Windows: `start.bat`
- Linux: 手動起動または任意のシェルスクリプト

---

## インストール

```bash
git clone https://github.com/xxxxx/emergency-contact-system.git
cd emergency-contact-system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 初期設定

初回起動時は、以下の初期値で管理画面に入れます。

```text
ADMIN_USER=admin
ADMIN_PASSWORD=OnlyYourPassword2026!
REGISTRATION_PASSWORD=ChangeMe
```

本番運用前に、管理画面の `/admin/settings` から必ず変更してください。

設定画面で変更できる項目:

- 管理者名
- 管理者パスワード
- 初回登録のあいことば
- 職種リスト
- VAPID設定
- 公開URL設定
- アプリ名・アイコン
- CSV自動書き出し

保存内容は `.env` に反映されます。`.env` は `main.py`、`start.command`、`start.bat` と同じプロジェクト直下に置かれます。

---

## 起動方法

### 通常起動

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

ブラウザで以下へアクセスします。

```text
http://127.0.0.1:8000
```

### macOS簡単起動

`start.command` をダブルクリックすると、以下を自動実行します。

- `.env` の読み込み
- 既存の8000番ポート利用プロセスの停止
- FastAPIサーバ起動
- ローカル画面をブラウザで表示
- 公開URLモードに応じたCloudflare Tunnel起動

`start.command` は実行権限が必要です。もし起動できない場合は以下を実行してください。

```bash
chmod +x start.command
```

### Windowsでの起動

1. Python 3.11以上をインストール
2. リポジトリを取得
3. 仮想環境を作成

```bat
python -m venv venv
```

4. 仮想環境を有効化

```bat
venv\Scripts\activate
```

5. 必要ライブラリを導入

```bat
pip install -r requirements.txt
```

6. 起動

`start.bat` をダブルクリックします。

または、手動で起動します。

```bat
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

`start.bat` は `.env` の `PUBLIC_URL_MODE` を読み込み、`dynamic` の場合は `cloudflared tunnel --url http://localhost:8000`、`fixed` の場合は `cloudflared tunnel run emergency` を起動します。

Windowsで `cloudflared.exe` が見つからない場合は、Cloudflare Tunnelをスキップしてローカル起動のみ行います。外部公開とPush通知を使う場合は、別途 `cloudflared` を導入してください。

---

### Dockerでの起動

Docker Desktop をインストール済みであれば、macOS / Windows / Linux で同じ手順で起動できます。

```bash
docker compose up -d --build
```

起動後、ブラウザで以下へアクセスします。

```text
http://127.0.0.1:8000
```

停止する場合:

```bash
docker compose down
```

ログを確認する場合:

```bash
docker compose logs -f
```

Docker環境では、SQLite DBと管理画面から保存される設定は `./data/` に保存されます。

- SQLite DB: `./data/emergency.db`
- Docker用設定ファイル: `./data/.env`
- 現在の一時公開URL: `./data/current_url.txt`
- 自動CSV書き出し: `./data/auto_exports/`
- アップロード資料: `./static/uploads/`

`plugins/`、`static/`、`templates/` はコンテナへマウントされるため、プラグイン、画面テンプレート、静的ファイルの変更もホスト側に残ります。

Docker構成にはCloudflare Tunnelは含めていません。外部公開やPush通知を本番運用する場合は、ホスト側の `cloudflared`、Cloudflare Tunnel、Nginx、リバースプロキシ等でHTTPS化してください。

---

## 初回利用の流れ

このシステムはPWAとしてホーム画面に追加して利用する前提です。

通常ブラウザでURLを開いた場合、登録フォームは表示されず、「ホーム画面に追加」案内だけが表示されます。

ホーム画面からPWAとして起動した場合のみ、初回登録フォームが表示されます。

登録項目:

- 名前
- 連絡先（任意、数字のみ）
- 職種
- あいことば

登録後は識別コードが自動生成され、同じ端末では次回以降、自分の利用者画面に戻ります。

---

## 利用者画面

利用者は以下の状態を送信できます。

- 元気です
- 困っています
- 助けてください

メモは状態に関係なく送信できます。メモだけ送信した場合は、直前の状態を引き継ぎます。

利用者自身による登録解除も可能です。

---

## 管理画面

管理画面はBasic認証で保護されています。

```text
http://127.0.0.1:8000/admin
```

管理画面で確認・操作できる内容:

- 登録者一覧
- 現在の状態
- コメント
- 最終応答日時
- 登録日時
- 返信率
- 職種別返信率
- 登録者の完全削除
- CSV出力
- CSV読み込み
- 一斉Push通知送信
- お知らせ管理
- Push定型文管理
- 公開URL表示
- 公開URLコピー
- 公開URL QRコード表示
- 通知グループ管理
- 利用者ごとの通知グループ割り当て

並び替え:

- 名前
- 日付
- 職種
- 色別
- 登録時刻
- 最終時刻

---

## CSV

### 登録者一覧CSV出力

出力項目:

- id
- name
- group_name（職種）
- occupation_memo（メモ）
- contact
- code
- active
- registered_at
- latest_status
- latest_comment
- latest_response_at
- notification_groups

### 応答履歴CSV出力

出力項目:

- response_id
- member_id
- name
- group_name（職種）
- status
- comment
- response_at

### CSV読み込み

管理画面から登録者CSVを読み込めます。

読み込み項目:

- name
- group_name
- occupation_memo（任意）
- staff_code（任意）
- contact（任意、数字のみ）
- notification_groups（任意）

重複は `staff_code`、または `name + group_name` でスキップします。CSVから読み込まれた職種が職種リストに存在しない場合も、エラーにはせずそのまま登録します。

`notification_groups` は `;` 区切りで複数指定できます。存在しない通知グループ名は自動作成されます。

例:

```csv
name,group_name,occupation_memo,staff_code,contact,notification_groups
山田太郎,医師,管理者,STAFF001,,"医師;管理者;災害対策本部"
```

CSVはUTF-8 BOM付きで出力されるため、Microsoft Excelで開きやすくなっています。

---

## アプリ表示設定

管理者は `/admin/settings` からアプリ名、短いアプリ名、PWAアイコンを編集できます。

アプリ名とアイコンは `static/manifest.json` に反映されます。端末のホーム画面に追加済みの場合、変更後のアイコンが反映されるまで、ホーム画面追加をやり直す必要がある場合があります。

---

## CSV自動書き出し

`/admin/settings` から、24時間ごとのCSV自動書き出しを有効または無効にできます。

有効な場合、登録者一覧CSVと応答履歴CSVを `auto_exports/` に自動保存します。

---

## 通知グループ

Emergency Contact System では、職種とは別に通知グループを作成できます。

職種は利用者の分類、通知グループはPush通知の送信対象として使います。

例:

- 職種: 医師
- 通知グループ: 管理者、災害対策本部、医師

管理者は通知送信時に「全員」または任意の通知グループを選択できます。

CSV読み込み時に `notification_groups` カラムを使うことで、初期所属グループをまとめて設定できます。

---

## お知らせ機能

Emergency Contact System には、職員向けお知らせページを追加できます。

管理者は `/admin/announcements` からお知らせを作成・編集し、利用者は `/staff` で閲覧できます。

本文にはMarkdownを利用できます。

---

## Push通知定型文

管理者は `/admin/push-templates` からPush通知の定型文を編集できます。

Push送信時には、定型文をプルダウンから選択し、タイトルと本文に反映できます。選択後も手入力で上書きできます。

---

## PWA / HTTPS

PWAとWeb Push通知を安定運用するにはHTTPSが必要です。

ローカルHTTPでも画面表示や基本操作は確認できますが、Push通知など一部ブラウザ機能は動作しない場合があります。

PWA関連ファイル:

- `static/manifest.json`
- `static/service-worker.js`
- `static/icons/`

---

## Web Push通知

管理画面から、通知登録済みの利用者へ一斉Push通知を送信できます。

利用者は自分の画面で「通知を有効にする」を押し、ブラウザの通知許可を行う必要があります。自動で通知許可は要求しません。

### VAPID鍵生成

```bash
python generate_vapid_keys.py
```

出力例:

```text
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY_FILE=vapid_private_key.pem
```

`.env` 例:

```text
VAPID_PUBLIC_KEY=生成された公開鍵
VAPID_PRIVATE_KEY_FILE=vapid_private_key.pem
VAPID_CLAIMS_SUB=mailto:admin@example.com
```

Apple Web PushではVAPID署名に失敗すると `403 Forbidden / BadJwtToken` が返ることがあります。秘密鍵は `generate_vapid_keys.py` が生成するPEMファイルを使い、`VAPID_CLAIMS_SUB` は必ず `mailto:` 形式にしてください。

VAPID設定は `/admin/settings` からも編集できます。

---

## 公開URL

このシステムはCloudflare Tunnelで外部公開できます。

### 可変URLモード

無料デモや短期試験では以下を利用できます。

```bash
cloudflared tunnel --url http://localhost:8000
```

`trycloudflare.com` の一時URLが発行されます。

注意:

- URLは起動ごとに変わります
- PWA登録はURL変更ごとにやり直しが必要です
- Push通知登録もURL変更ごとにやり直しが必要です
- 継続運用には向きません

`start.command` で可変URLモードを使う場合、Cloudflareの一時URLは `current_url.txt` に保存されます。

### 固定URLモード

継続運用では、独自ドメインとCloudflare Named Tunnel等の利用を推奨します。

例:

```text
https://example.com
```

固定URLでは、PWA登録やPush通知登録を維持しやすくなります。

公開URLの運用モードは `/admin/settings` から変更できます。

固定URLモードでターミナルを再起動したい場合は、起動中のターミナルを `control + C` で停止してから、もう一度 `start.command` をダブルクリックしてください。`start.command` は既存の8000番ポートのサーバを停止してから再起動します。

### Cloudflare Tunnel 起動モード

`start.command` は2種類の公開URLモードに対応しています。

#### 可変URLモード

```text
PUBLIC_URL_MODE=dynamic
```

以下を使用します。

```bash
cloudflared tunnel --url http://localhost:8000
```

一時URLが発行されますが、起動ごとに変わります。

#### 固定URLモード

```text
PUBLIC_URL_MODE=fixed
```

以下を使用します。

```bash
cloudflared tunnel run emergency
```

Cloudflare Named Tunnel と独自ドメイン設定が必要です。

ドメイン取得だけでは固定URL運用はできません。取得したドメインをCloudflare管理下に置き、Named Tunnel作成、DNSルート作成、`config.yml` 作成まで完了してから `cloudflared tunnel run emergency` でFastAPIへ接続します。

流れ:

```text
固定ドメイン取得
↓
Cloudflare管理下に置く
↓
Named Tunnel作成
↓
DNSルート作成
↓
config.yml作成
↓
cloudflared tunnel run emergency
↓
FastAPIへ接続
```

固定URLは `~/.cloudflared/config.yml` 側で管理します。

固定URLモードを使う場合は、事前に以下が必要です。

- `cloudflared tunnel login`
- `cloudflared tunnel create emergency`
- `cloudflared tunnel route dns emergency <固定URL>`
- `~/.cloudflared/config.yml` の作成

### 固定URL運用時の手動起動

固定URL運用では、Cloudflare Named Tunnel を使用します。

手動起動する場合:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

別ターミナルで:

```bash
cloudflared tunnel run emergency
```

`start.command` を使用すると、FastAPIとNamed Tunnelをまとめて起動できます。

`PUBLIC_URL_MODE=fixed` の場合、`start.command` は `cloudflared tunnel --url http://localhost:8000` を使用しません。

Named Tunnel名は標準で `emergency` です。変更したい場合は `.env` に以下を追加してください。

```text
CLOUDFLARED_TUNNEL_NAME=emergency
```

---

## 技術構成

- Python
- FastAPI
- SQLite
- Jinja2
- HTML/CSS/JavaScript
- PWA
- Web Push

---

## 現在の実装状況

実装済み:

- 利用者登録
- 識別コード自動生成
- 職種リスト編集
- あいことば編集
- 状態報告
- メモ送信
- 管理画面
- Basic認証
- 登録解除
- 登録者完全削除
- CSV出力
- CSV読み込み
- 返信率表示
- PWA
- Service Worker
- Web Push通知
- 公開URL設定
- Cloudflare一時URL取得

---

## 注意点

- 管理者パスワードやVAPID秘密鍵をGitHubに公開しないでください。
- `.env`、`vapid_private_key.pem`、`emergency.db` はGit管理しないでください。
- 可変URLモードでは、URL変更のたびにPWA登録とPush通知登録のやり直しが必要です。
- 管理画面のQRコードはアプリ内部で生成します。

---

## Ver.1.1の変更点

- 初回登録画面をPWA前提の導線に変更し、通常ブラウザではホーム画面追加の案内を表示するようにしました。
- 登録項目を整理し、識別コードは自動生成、職種は選択式、あいことばで初回登録を制限する形にしました。
- 連絡先番号を任意入力として追加しました。数字のみ保存されます。
- 同じ名前と職種での二重登録を防止するようにしました。
- 管理画面にBasic認証、登録者削除、返信率表示、返信率リセット、並び替え機能を追加しました。
- 登録者削除と利用者の登録解除は、応答履歴・Push購読・通知グループ所属を含めた完全削除方式に変更しました。
- 管理画面の並び替えは、項目クリックで昇順・降順を切り替えられるようにしました。
- 管理画面にメモ欄を追加しました。メモはCSVに保存され、result画面にも表示されます。
- 登録者一覧CSV・応答履歴CSVの出力、登録者CSV読み込み、24時間ごとのCSV自動書き出しに対応しました。
- CSVには連絡先、メモ、通知グループを含められるようにしました。
- PWA対応として manifest、Service Worker、アイコン設定、ホーム画面追加案内を追加しました。
- Web Push通知に対応し、VAPID鍵生成スクリプトと管理画面からのVAPID設定編集を追加しました。
- 管理画面から一斉通知、選択した人だけ通知、応答がない人だけ通知、通知グループ通知を送れるようにしました。
- 通知グループ機能を追加し、職種とは別にPush通知の送信対象を管理できるようにしました。
- 利用者画面に通知許可ボタン、通知完了表示、結果を見るボタン、お知らせボタンを追加しました。
- result画面を追加し、返信のあった人だけを表示する確認画面にしました。連絡先番号は表示しません。
- 院内お知らせCMSを追加し、管理画面からお知らせを作成・編集し、利用者は `/staff` で閲覧できるようにしました。
- Push通知定型文の管理機能を追加し、送信時にプルダウンから文面を反映できるようにしました。
- 管理画面の設定からアプリ名、短いアプリ名、PWAアイコン、職種リスト、管理者ログイン、あいことばを編集できるようにしました。
- 公開URL設定を追加し、可変URLモードと固定URLモードを切り替えられるようにしました。
- Cloudflare一時URLの表示、コピー、内部生成QRコード表示に対応しました。
- `start.command` をCloudflare可変URLモードと固定URLモードの両方に対応させました。
- Windows向けの `start.bat` を追加し、Windowsでも起動しやすくしました。

---

## Ver.1.3の変更点

- Android端末でFCM送信がHTTP 201成功でも通知が表示されない問題を切り分けるため、管理画面にPushテストモードを追加しました。
- Pushテストモードは `/admin/settings` からON/OFFできます。通常運用ではOFFにできます。
- 管理画面のPush送信テストで、endpoint種別、HTTP status code、response body、例外種別、例外メッセージ、送信payloadを確認できるようにしました。
- Android向けにFCM endpointだけへ送る「Android Pushデバッグ送信」を追加しました。
- 通常のPush送信結果に、Apple / FCM / その他ごとの成功数・失敗数を表示するようにしました。
- 404 / 410 の失効したPush購読は自動で inactive にするようにしました。
- 403 の場合はVAPID鍵不整合の可能性として警告表示するようにしました。
- Service Workerのpushイベント処理を堅牢化し、payloadが空、JSONでない、JSON parseに失敗した場合でも通知表示処理が落ちないようにしました。
- Service Workerにバージョン情報を追加し、更新状態を確認できるようにしました。
- 職員向け画面の起動時にService Workerを自動登録・自動更新するようにしました。失敗時は画面には大きく出さず、console.warnに留めます。
- 「通知を許可」ボタン内に、Service Worker更新、version確認、Push購読取得、サーバ登録を内蔵しました。
- Push登録時に、同じ利用者の古いsubscriptionをinactiveにしてから現在のsubscriptionを保存するようにしました。
- Androidでホーム画面アイコン削除後に古い端末情報が残る場合に備え、初期画面に「端末内の登録情報を消去」を追加しました。
- 職員向け画面からデバッグ用ボタンと詳細診断表示を削除し、本番向けにUIを整理しました。
- 管理画面のPush送信前に「通知を送りますか？」の確認アラートを追加しました。
- staff画面に戻るボタンを追加し、スマホで右側が見切れないよう横幅調整を行いました。
- result画面は返信のあった人だけを表示し、登録者一覧と連絡先番号は表示しないようにしました。
- 「職種メモ」の表示名を「メモ」に変更しました。CSV内部項目名 `occupation_memo` は互換性のため維持しています。

---

## Ver.1.3.2の変更点

- 管理画面の「返信率をリセット」の表示を「返信をリセット」に変更しました。
- 管理画面の職種ソートは、職種名を変更せず、設定画面の職種リスト順で並ぶようにしました。
- デフォルト職種順では、医師、看護師、看護助手の順に表示されます。
- 管理画面の登録者一覧から識別コードの表示と識別コードのソートを外しました。識別コードはCSVで管理します。
- 登録日時は日付のみ、最終応答日時は分までの短い表示にしました。
- 通知グループが未所属の場合は `-` と表示するようにしました。
- 通知グループ編集リンクを `[i]` 表示に変更しました。
- メモ欄の保存ボタンを非表示にし、Enter / Returnキーで保存できるようにしました。
- 管理画面のお知らせ管理ボックスと `/admin/announcements` のボタン表示を統一しました。

---

## プラグイン機能

Emergency Contact System の公開版は、安否確認、メンバー管理、Push通知を core 機能として維持します。

施設ごとの追加機能は、同一リポジトリ内の `plugins/` に任意プラグインとして追加できます。公開版ではデフォルト無効です。

プラグイン構成例:

```text
plugins/<plugin_name>/router.py
plugins/<plugin_name>/templates/
plugins/<plugin_name>/static/
plugins/<plugin_name>/models.py
```

有効化する場合は `.env` に `ENABLED_PLUGINS` を設定します。

```text
ENABLED_PLUGINS=calendar,cms,phonebook
```

管理画面の `/admin/settings` にある「プラグイン」欄からも、同じ設定を変更できます。
保存後はアプリを再起動すると反映されます。

未設定または空欄の場合、プラグインのURLや管理画面メニューは表示されません。

現在はサンプルとして `calendar` プラグインを追加しています。

```text
ENABLED_PLUGINS=calendar
```

この設定で起動すると `/calendar` が有効になり、管理画面に有効化中のプラグインとして表示されます。

### 予定カレンダー

`calendar` プラグインでは、事務所や管理者が管理するGoogleカレンダー等を予定の原本として、PWA側に読み取り専用で表示できます。

Google認証やOAuthは使用せず、公開ICS URLを `.env` に設定します。
管理画面の `/admin/settings` にある「予定カレンダー」欄からも入力できます。

```text
ENABLED_PLUGINS=calendar
CALENDAR_ICS_URL=https://calendar.google.com/calendar/ical/...
```

表示URL:

```text
/calendar
```

表示内容:

- 日付
- 開始時刻
- 終了時刻
- タイトル
- 場所

予定は今日、明日、今週、今後半年に分けて表示します。
取得結果は約10分キャッシュし、毎回Googleへアクセスしすぎないようにしています。

取得に失敗した場合は、画面に「予定を取得できません」と表示します。
管理画面と設定画面では、現在の `CALENDAR_ICS_URL` と最終取得時刻を確認できます。

### survey プラグイン

`survey` プラグインでは、既存のメンバーと職種グループを使って、出欠確認や簡単なアンケートを実施できます。

公開版ではデフォルト無効です。有効化する場合は `.env` または `/admin/settings` の「プラグイン」欄に `survey` を追加し、アプリを再起動してください。

```text
ENABLED_PLUGINS=survey
```

`calendar` と併用する場合:

```text
ENABLED_PLUGINS=calendar,survey
```

管理者向け:

- `/admin/surveys` からアンケートを作成できます。
- 対象は「全員」「職種グループ」「通知グループ」から選択できます。
- 職種グループは既存の `members.group_name` を利用します。
- 通知グループは、既存の通知グループ管理で作成した任意グループと所属設定を利用します。
- 回答形式は、出席/欠席/未定、はい/いいえ、選択式、自由記載に対応しています。
- 作成後、対象グループへPush通知を送信できます。
- 集計画面では回答数、未回答数、回答内容、回答者一覧、未回答者一覧を確認できます。
- 集計結果は「結果CSV出力」からCSV出力できます。対象者全員を出力し、回答済み / 未回答も分かるようにしています。

職員向け:

- 職員画面に、自分が対象となる未回答アンケートが表示されます。
- 職種グループ対象の場合は職種一致、通知グループ対象の場合は所属グループ一致、全員対象の場合は全員に表示されます。
- 回答済みのアンケートは「回答済み」と表示されます。
- 回答は1人1回を基本とし、再回答すると前回の回答を上書きします。

セキュリティ:

- 職員は自分の職種グループ対象のアンケートのみ回答できます。
- アンケート作成、通知送信、集計閲覧、CSV出力は管理者認証が必要です。

---

## Ver.1.4の変更点

- `calendar` プラグインの予定表示を職員向け user 画面にも追加しました。
- `ENABLED_PLUGINS` に `calendar` が含まれる場合のみ、user画面の「お知らせ」の下に「予定」を表示します。
- plugin が無効の場合、予定セクションはHTML上にも表示されません。
- Googleカレンダーの公開ICS URLを `CALENDAR_ICS_URL` で設定し、読み取り専用で予定を表示します。
- user画面では今日、明日、今後7日間、今後半年の予定をカード形式で表示します。
- 表示項目は、日付、開始時刻、終了時刻、タイトル、場所、説明です。
- 終日予定は「終日」と表示します。
- 予定がない場合は「今後の予定はありません」と表示します。
- 取得失敗時は職員画面では「予定を取得できません」とだけ表示します。
- 予定取得結果は約10分キャッシュし、Googleへ毎回アクセスしすぎないようにしました。
- 管理画面では、calendar plugin が有効な場合のみ、`CALENDAR_ICS_URL` の設定有無、最終取得時刻、取得状態を表示します。

設定例:

```text
ENABLED_PLUGINS=calendar
CALENDAR_ICS_URL=https://calendar.google.com/calendar/ical/.../basic.ics
```

Google認証やOAuth、予定編集機能は実装していません。PWA側は読み取り専用表示のみです。

### viewer プラグイン

`viewer` プラグインでは、PDFや画像を職員向け画面で閲覧できます。

BCP、アクションカード、災害マニュアルなどを掲載する用途を想定しています。
公開版ではデフォルト無効です。有効化する場合は `.env` または `/admin/settings` の「プラグイン」欄に `viewer` を追加し、アプリを再起動してください。

```text
ENABLED_PLUGINS=viewer
```

他のプラグインと併用する場合:

```text
ENABLED_PLUGINS=calendar,survey,viewer
```

管理者向け:

- `/admin/viewer` から資料を登録できます。
- セクション表示名を変更できます。初期値は「資料閲覧」です。
- PDF / PNG / JPG / JPEG / WebP をアップロードできます。
- 登録できる資料は最大10件程度です。
- ファイルサイズ上限は20MBです。
- タイトル、説明、表示/非表示、並び順を編集できます。
- 資料は削除できます。

職員向け:

- viewer plugin が有効で、表示中の資料がある場合のみ user画面に表示されます。
- user画面では「お知らせ」の下、「予定」の上に表示されます。
- 資料はカード形式で表示され、PDFの場合は「PDFを開く」、画像の場合は「画像を表示」と表示します。
- PDFは画像変換せず、中間の閲覧画面を挟まずにブラウザ標準のPDFビューアで直接開きます。複数ページPDFも全ページ閲覧できます。

セキュリティ:

- アップロード、編集、削除は管理者のみ可能です。
- 職員は閲覧のみ可能です。
- 実行可能ファイルは登録できません。
- ファイル名はランダム名に変換して保存し、同名上書き事故を防ぎます。
- 保存先は `static/uploads/viewer/` です。

### phonebook プラグイン

`phonebook` プラグインでは、近隣病院、行政、消防、中毒センター、災害時直通ダイヤル、業者などを電話帳として登録できます。

公開版ではデフォルト無効です。有効化する場合は `.env` または `/admin/settings` の「プラグイン」欄に `phonebook` を追加し、アプリを再起動してください。

```text
ENABLED_PLUGINS=phonebook
```

他のプラグインと併用する場合:

```text
ENABLED_PLUGINS=calendar,survey,viewer,phonebook
```

管理者向け:

- `/admin/phonebook` からカテゴリと連絡先を登録できます。
- 初期カテゴリとして、災害・救急、医療機関、中毒・感染症、行政・消防、業者、院内を用意しています。
- 連絡先には電話番号2つ、電話メモ、メール、Web、住所、メモを登録できます。
- 表示/非表示、並び順、ピン留め、災害時のみ表示を設定できます。
- CSV読み込み・CSV出力に対応しています。

職員向け:

- phonebook plugin が有効な場合のみ、user画面の「お知らせ」の下に「電話帳」ボタンを表示します。
- 件数が多くなるため、user画面には連絡先一覧を直接表示しません。
- `/phonebook` の独立ページで電話帳を閲覧できます。
- 検索欄とカテゴリ絞り込みを利用できます。
- ピン留め連絡先は上部に表示されます。
- 電話番号とメールアドレスは文字として表示され、タップすると電話・メール画面を開けます。
- Web、地図ボタンを表示し、スマートフォンからワンタップで開けます。

用途例:

- 近隣病院
- 消防、行政
- 中毒センター、感染症相談先
- 災害時直通ダイヤル
- 酸素業者、医療ガス業者
- 情報システム業者、施設管理業者

---

## メンテナンス表示

PWAとして一度読み込まれた端末では、サーバ停止中や通信失敗時にService Workerが `static/maintenance.html` を表示します。

表示文言:

```text
ただいまメンテナンス中です
```

注意:

- FastAPIサーバ自体が停止している場合、FastAPIは応答できません。
- そのため、この表示はService Workerが有効で、メンテナンスページが事前にキャッシュされている端末で動作します。
- 初回アクセス端末やService Worker未登録のブラウザでは、ブラウザやCloudflare側のエラー画面になる場合があります。
- 本番で完全に独自のメンテナンス画面を出す場合は、Nginx、Cloudflare、またはリバースプロキシ側で503エラーページを設定してください。

---

## 通常モード / 災害モード

Emergency Contact System は、管理画面から運用モードを切り替えられます。

### 通常モード

平常時の院内ポータルとして使うモードです。

- 職員画面では安否確認ボタンを表示しません。
- 「元気です」「困っています」「助けてください」などの災害用ボタンは非表示になります。
- メモ送信フォームと「結果を見る」も非表示になります。
- お知らせ、予定、アンケート、通知設定などの平常時機能は表示されます。
- 平常時に職員が誤って安否確認を送信しないようにします。

### 災害モード

災害時や緊急時に安否確認を行うモードです。

- 職員画面上部に「災害モード中」と表示します。
- 安否確認ボタン、メモ送信、結果閲覧を表示します。
- 既存の安否確認送信機能をそのまま利用します。

### 管理画面での切り替え

管理画面の一番上にある「運用モード」から切り替えます。

- 通常モード
- 災害モード

災害モード中は、管理画面上部に赤い帯で「災害モード中」と表示されます。

モードは `settings` テーブルの `disaster_mode` に保存されます。

---

## Ver.1.5の変更点

- 通常モード / 災害モードを追加しました。通常モードでは職員画面の安否確認ボタン、メモ送信、結果閲覧を非表示にし、平常時の誤送信を防ぎます。
- 管理画面上部の運用モード切り替えボタンを大きくし、「管理画面」の右側に並べるレイアウトに整理しました。
- サーバ停止時に、Service Workerが利用できる端末では「ただいまメンテナンス中です」を表示するようにしました。
- `viewer` プラグインを追加しました。PDF / PNG / JPG / JPEG / WebP を管理画面から登録し、職員画面で閲覧できます。
- viewer のPDFは画像化せず、PDFファイルを直接開く方式に変更しました。複数ページPDFもブラウザ標準ビューアで閲覧できます。
- viewer 管理画面の「資料を追加」ボタン横に、対応形式、20MB上限、最大10件の案内を表示しました。
- 職員画面の「お知らせ」ボタンに、公開中のお知らせ件数を赤いバッジで表示するようにしました。
- 職員画面右上に「再度開く」ボタンを追加しました。
- 登録用QRコードの表示名を整理しました。
- 管理画面のボタン配置を整理し、CSV、設定、Push通知、お知らせ管理、プラグインの導線を分かりやすくしました。
- 管理画面の「設定」ボタンに歯車アイコンを付け、プラグイン欄からも設定画面へ移動できるようにしました。
- 管理画面の保存、ソート、CSV読み込み、メモ保存後に、直前のスクロール位置へ戻るようにしました。
- 登録者一覧の初期ソートを「職種」にしました。
- 登録者一覧の「メモ」は空欄時に目立たない表示へ変更し、クリック時だけ入力枠を表示するようにしました。
- 初回登録時、選択した職種と同名の通知グループが存在する場合、その通知グループへ自動所属するようにしました。
- お知らせ管理のトップ表示を省スペース化し、詳細操作は `/admin/announcements` に集約しました。
- お知らせ編集画面の「戻る」は管理画面トップへ戻るようにしました。
- `calendar` プラグインの表示名を「予定」に変更し、病院以外の施設でも使いやすい文言にしました。
- `survey` プラグインでは、職種グループ、通知グループ、全員を対象にしたアンケート・出欠確認に対応しました。
- アンケート結果画面にCSV出力を追加しました。対象人数が多い場合でもExcel等で確認できます。
- 設定画面の一番下に「全て初期化」ボタンを追加しました。登録者、応答、お知らせ、アップロード資料は削除せず、設定だけを初期値へ戻します。
- Gitに個人情報や運用データが混ざらないよう、`.env`、DB、VAPID秘密鍵、Cloudflareログに加えて、`static/uploads/` も除外対象にしました。

Git管理前の注意:

- 実運用のPDF、画像、GoogleカレンダーICS URL、VAPID鍵、Cloudflare URL、SQLite DBはリポジトリに含めないでください。
- アップロード資料は `static/uploads/` に保存されますが、Git対象外です。
- GoogleカレンダーURLは `.env` または管理画面の設定で管理し、READMEには実URLではなく例だけを記載してください。

---

## Ver.1.5.1の変更点

- `phonebook` プラグインを追加しました。近隣病院、消防、行政、中毒センター、災害時直通ダイヤル、業者などを電話帳として管理できます。
- phonebook は公開版ではデフォルト無効です。利用する場合は `ENABLED_PLUGINS=phonebook` を設定します。
- user画面には「電話帳」ボタンだけを表示し、連絡先一覧は `/phonebook` の独立ページで表示する仕様にしました。
- `/phonebook` では検索、カテゴリ絞り込み、ピン留め連絡先の上部表示に対応しました。
- 電話番号は2つ登録できます。電話番号とメールアドレスは文字として表示し、タップで電話・メール画面を開けます。
- Webと地図はボタンとして表示します。
- phonebook 管理画面では、カテゴリ、名称、組織名、電話番号、電話メモ、メール、Web、住所、メモ、並び順、ピン留め、表示/非表示を編集できます。
- phonebook 管理画面にCSV読み込み・CSV出力を追加しました。
- phonebook 管理画面は、連絡先一覧を一番上に表示し、入力欄を1行配置にして見やすくしました。
- phonebook 管理画面では、重複していた「非表示」ボタンを削除し、「表示する」チェックボックスへ整理しました。
- phonebook 管理画面では「カテゴリ一覧」を省略し、「カテゴリ追加」は連絡先追加の下へ移動しました。
- 通常モードでは、管理画面の安否確認用Push通知ボックスを操作できないようにしました。
- 通常モード中に `/admin/push/send` へ直接送信しても、サーバ側で拒否します。
- お知らせ管理からのお知らせ通知は、通常モードでも送信できます。

---

## Ver.1.5.2の変更点

- 外部公開時の安全性を見直し、登録済み端末Cookieがない場合は職員向けページを直接閲覧できないようにしました。
- `/result` は登録済み端末向けの結果画面として保護し、管理者向けにはBasic認証付きの `/admin/result` を追加しました。
- 管理画面の「返信率」ボックスに「結果を見る」ボタンを追加し、`/admin/result` へ移動できるようにしました。
- `/staff`、`/phonebook`、`/calendar`、`/viewer/{id}`、`/viewer/{id}/file` は登録済み端末Cookieがない場合に表示しないようにしました。
- `/user/{code}` を開いたときに登録済み端末Cookieを再保存するようにし、職員向けページへの移動が安定するようにしました。
- phonebook の「戻る」は、保存済み利用者コードがある場合に `/user/{code}` へ戻るようにしました。
- phonebook 管理画面のCSV読み込みボタン名を「CSVファイルを選択」に変更し、CSV出力ボタンの右側へ配置しました。
- phonebook 管理画面では連絡先一覧を一番上に移動し、入力欄を「名称：入力ボックス」のような1行配置に整理しました。
- phonebook 管理画面では、連絡先一覧の「災害時のみ表示」と重複していた「非表示」ボタンを削除しました。
- phonebook 管理画面では「カテゴリ一覧」を省略し、「カテゴリ追加」は連絡先追加の下へ移動しました。
- 自動CSV書き出し先の `auto_exports/` をGit除外対象に追加しました。
- 管理画面上部の運用モードボタン文言を「通常モード」「災害モード」に変更しました。

---

## Ver.1.6の変更点

- Docker Desktop で起動できるように、`Dockerfile`、`compose.yml`、`.dockerignore` を追加しました。
- Dockerイメージは `python:3.12-slim` を使用し、`requirements.txt` から必要ライブラリを導入します。
- Docker起動時は `uvicorn main:app --host 0.0.0.0 --port 8000` でFastAPIを起動します。
- `docker compose up -d --build` だけでmacOS / Windows / Linuxから起動できる構成にしました。
- `compose.yml` に `restart: unless-stopped` と `TZ=Asia/Tokyo` を設定しました。
- SQLite DBを `./data/emergency.db` に保存するようにし、コンテナを作り直しても登録者、応答、設定が残るようにしました。
- Docker環境向けに `DB_PATH`、`ENV_FILE`、`CURRENT_URL_FILE`、`AUTO_EXPORT_DIR`、`VIEWER_UPLOAD_DIR`、`PLUGIN_DIR` の環境変数を利用できるようにしました。
- `plugins/`、`static/`、`templates/` をボリュームとしてマウントし、プラグイン、静的ファイル、テンプレート、アップロード資料をホスト側に残せるようにしました。
- `.dockerignore` に `.env`、SQLite DB、仮想環境、キャッシュ、一時ファイル、Cloudflareログ、VAPID秘密鍵、アップロード資料などを追加し、Dockerビルドに不要なファイルや機密情報が入らないようにしました。
- `.gitignore` に `data/` を追加し、Docker運用時のDBや設定ファイルがGitへ混入しないようにしました。
