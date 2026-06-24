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

## 初回利用の流れ

このシステムはPWAとしてホーム画面に追加して利用する前提です。

通常ブラウザでURLを開いた場合、登録フォームは表示されず、「ホーム画面に追加」案内だけが表示されます。

ホーム画面からPWAとして起動した場合のみ、初回登録フォームが表示されます。

登録項目:

- 名前
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
- 登録者の無効化
- CSV出力
- CSV読み込み
- 一斉Push通知送信
- 公開URL表示
- 公開URLコピー
- 公開URL QRコード表示

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
- code
- active
- registered_at
- latest_status
- latest_comment
- latest_response_at

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
- staff_code（任意）

重複は `staff_code`、または `name + group_name` でスキップします。CSVから読み込まれた職種が職種リストに存在しない場合も、エラーにはせずそのまま登録します。

CSVはUTF-8 BOM付きで出力されるため、Microsoft Excelで開きやすくなっています。

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
- 登録者無効化
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
