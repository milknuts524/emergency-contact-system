# emergency-contact-system
Emergency Alert System in Hospital

# Emergency Contact System

Emergency Contact System は、利用者の状態報告と管理者による状況集約を目的とした軽量なWebアプリケーションです。
シンプルな入力とリアルタイムな状況把握を重視し、Python と FastAPI を用いて構築されています。
Python、FastAPI、SQLite を利用して構築されており、単一PC上で動作します。
難しいコマンド入力が苦手な方がでも、start.commandをダブルクリックすることで、サーバ起動、ブラウザ立ち上げを自動実行できます。
主に企業内での運用を想定していますが、家庭での安否確認などにもご利用いただけます。

（運用は自己責任でお願い致します）

---

**********************************************

## 初期設定

初回起動時は、管理者アカウントおよび登録パスワードを設定してください。

開発時のサンプル設定：

ADMIN_USER = "admin"

ADMIN_PASSWORD = "OnlyYourPassword2026!"

REGISTRATION_PASSWORD = "ChangeMe"

### 注意

- 本番運用前に必ず変更してください。
- 管理者パスワードを GitHub に公開しないでください。
- 複数環境で運用する場合は `.env` ファイル等で管理することを推奨します。
- 管理画面(`/admin`)は Basic 認証で保護されます。

**********************************************



# システム要件

動作確認環境

- macOS
- Python 3.11 以上
- FastAPI
- Uvicorn

---

# インストール

リポジトリを取得します。

git clone https://github.com/xxxxx/emergency-contact-system.git
cd emergency-contact-system

仮想環境を作成します。

python3 -m venv venv
source venv/bin/activate

必要なライブラリをインストールします。

pip install fastapi uvicorn jinja2 python-multipart

分かりにくい方は、これらを全てChat GPTなどに投げればなんとかなります。

---


# 起動方法

通常起動

source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

ブラウザで以下へアクセスします。

http://127.0.0.1:8000

---

# 簡単起動

macOSでは付属の

start.command

をダブルクリックすることで、

- FastAPIサーバ起動
- ブラウザ起動

を自動実行できます。

すでに8000番ポートが使われている場合は、既存プロセスを停止してから起動する仕様です。

開発中や個人利用時はこちらを推奨します。

---

# HTTPS / PWA 運用メモ

現在の `start.command` 起動では、ローカルHTTPで動作します。

http://127.0.0.1:8000

PWAとしてホーム画面に追加する準備として、`static/manifest.json`、`static/service-worker.js`、`static/icons/` を追加しています。

PWA / Push通知を本番運用するにはHTTPSが必要です。本番環境では、Nginx + Let's Encrypt、または Cloudflare Tunnel 等を利用してHTTPS化してください。

ローカルLAN内の試験では、HTTPでも基本的な画面表示や状態送信の動作確認は可能です。ただし、Push通知など一部のブラウザ機能はHTTPSでないと利用できません。

Push通知そのものは今回の範囲には含めず、次段階で実装予定です。

---


# 主な機能

## 利用者登録

利用者は以下を入力して登録します。

* 名前
* グループ
* 登録パスワード

システムは識別コードを自動生成します。

---

## 状態報告

利用者は現在の状態をボタンで送信できます。

標準設定

* OK
* Need Assistance
* Emergency

表示文言は用途に応じて変更可能です。

---

## コメント送信

利用者は任意でコメントを送信できます。

例

* 現在地
* 状況説明
* 補足情報

---

## 管理画面

http://127.0.0.1:8000/admin

管理者は登録者の状態を一覧表示できます。

管理者認証が必要です。初回起動時に求められます。

上記の注意点を読み、必ずmain.pyの中にある該当項目を編集して下さい。

管理画面から以下を出力できます。

- 登録者一覧CSV
- 応答履歴CSV

UTF-8(BOM付き)形式のため、Microsoft Excelで直接開くことができます。


表示項目

* 名前
* グループ
* 現在の状態
* コメント
* 登録日時
* 最終応答日時
* 識別コード

---

## 登録管理

利用者自身による登録解除が可能です。

管理者は登録者を無効化できます。

データは削除せず、active フラグによって管理します。

---

## CSV出力

管理画面からCSVを出力できます。

### 登録者一覧CSV

出力内容

* id
* name
* group_name
* code
* active
* registered_at
* latest_status
* latest_comment
* latest_response_at

### 応答履歴CSV

出力内容

* response_id
* member_id
* name
* group_name
* status
* comment
* response_at

UTF-8 with BOM形式で出力し、Excelで利用できます。

---

# 技術構成

* Python
* FastAPI
* SQLite
* Jinja2
* HTML/CSS

---

# 設計方針

本システムは以下を重視しています。

* シンプルな操作
* モバイル対応
* 軽量な構成
* 導入容易性
* 管理容易性

利用者が入力する情報を最小限にし、管理者が状況を把握しやすい設計を目指しています。

---

# 現在の実装状況

Version 0.1

実装済み

* 利用者登録
* 識別コード自動生成
* 状態報告
* コメント送信
* 管理画面
* Basic認証
* 登録解除
* 登録者無効化
* CSV出力
* スマートフォン対応UI
* PWA準備

未実装

* Push通知

---

# 開発メモ

本システムは特定用途に依存しない汎用的な状態報告システムとして設計されています。

運用環境に応じて、

* 状態ボタン
* 登録項目
* 集計項目

を変更することで様々な用途へ適用できます。

機能追加を行う際も、シンプルさと軽量性を維持することを優先してください。
