# HTTPS・保存DB暗号化の導入手順

2026-10-22。コードの変更だけでは、別端末で動いているmini PCには反映されません。
移行中はアプリを停止し、作業前の版 `2f633b6` を参照できる状態にしてください。

すでに暗号化・復旧が完了している場合は再移行せず、[復旧後の整合性修正手順](STORAGE_FIX_UPDATE.md)を使用してください。

## 変更内容と保護範囲

- 公開通信はCloudflare TunnelのHTTPSを利用。HTTPでの外部アクセスはHTTPSへ308転送。
- 接続先名を検証。標準でlocalhost、ループバックIP、一時トンネルのドメインを許可し、`FIXED_PUBLIC_URL` のホスト名も許可。
- `ALLOWED_HOSTS` を設定する場合はカンマ区切りで全ホストを列挙（ワイルドカード `*` だけの設定は避ける）。
- ネイティブ起動は127.0.0.1だけで待ち受け、同一PC内のcloudflaredから来る転送情報だけを信頼。`--reload` は使わない。
- HTTPS応答にHSTSを設定。有効期間は30日、他サブドメインには適用しない。
- 同じPC内の `http://127.0.0.1:8000` は保守用に残す。院内LANからIPアドレスで直接アクセスする従来の方法は使えなくなる。
- DB全体はSQLCipherで暗号化。鍵なし・誤った鍵・暗号化設定に平文DBを渡した場合は起動を停止し、平文に切り替えない。
- DB暗号鍵はランダムな256ビット鍵。環境変数には鍵本体ではなく保存ファイルのパスだけを設定。
- 日次の自動CSV出力は暗号化DB使用時にAES-GCMで `.csv.enc` として保存。認証付きの手動CSVダウンロードは通常のCSVとして残る。
- これまでの資料、手動CSV、旧DB、既存バックアップ、`.env` は今回のDB暗号化で自動的には暗号化されない。

DBファイルだけが持ち出された場合に有効。PC上のアプリ権限を乗っ取られると鍵も読み取られる可能性がある。ディスク暗号化、アクセス制限、認証強化も別途必要。

## Windows・start.batの場合

1. 現在のFastAPIとCloudflareのウィンドウを閉じる。新しい起動処理は他のプロセスを強制停止しない。
2. 更新したコードを配置。古い`.env`、DB、資料、秘密鍵は上書きしない。
3. プロジェクトのターミナルで依存関係を更新。

```bat
venv\Scripts\python.exe -m pip install -r requirements.txt
```

SQLCipherは `sqlcipher3==0.6.4` の配布済みバイナリーを利用する。WindowsではPython 3.9〜3.13の対応wheelを公式PyPIで確認済み。インストールに失敗したら暗号化なしで起動せず、Pythonの版・CPU構成を確認する。

4. 平文DBから暗号化DBを作り、検証が成功した場合だけ`.env`を更新。

```bat
venv\Scripts\python.exe scripts\secure_storage.py migrate --activate
```

標準の入力は `.env` の `DB_PATH`、未設定なら `emergency.db`。出力は `emergency.encrypted.db`、鍵は `secrets/database.key`。既存の出力ファイル・鍵は上書きしない（既存の鍵を指定した移行では同じ鍵を使用）。移行先のスキーマ・件数・整合性・再読込を確認する。元DBは保持する。

5. `.env`に公開URL設定があることを確認。

```dotenv
PUBLIC_URL_MODE=fixed
FIXED_PUBLIC_URL=https://emergency.tohyama.cc
CLOUDFLARED_TUNNEL_NAME=emergency
```

Named Tunnelの既存設定で接続先を `http://127.0.0.1:8000` にする。`localhost` がIPv6を選択すると接続できない場合がある。`~/.cloudflared/config.yml`、またはCloudflare管理画面の接続先を変更する。トンネルの認証ファイルやトークンをGitに追加しない。

6. 暗号鍵を別保管先にコピーし、読み出せる担当者を決める。Windowsでは `secrets` フォルダーのアクセス権を運用アカウントと必要な管理者だけにする。鍵をDBと同じ共有フォルダーへ配布しない。
7. `start.bat` で起動し、スマホから公開HTTPS URLで登録済み利用者・管理画面・通知・資料閲覧を確認。

macOSでは依存関係更新・移行を `venv/bin/python` で実行し、`start.command` で起動する。

## Dockerの場合

画面操作を含む順番は[Docker Desktopでの移行手順](DOCKER_MIGRATION_STEPS.md)を参照。mini PCへのPythonの追加は不要です。
アプリを `docker compose down` で停止し、フォルダーをバックアップして更新ファイルを配置してから、Dockerで次を実行する。

```text
docker compose run --rm --build storage-tools migrate --source /app/data/emergency.db --target /app/data/emergency.encrypted.db
```

鍵は `secrets/database.key` に自動生成される。`--activate` は使用しない。compose側が保存先と鍵のパスを設定する。storage-toolsは移行・バックアップ時だけ起動し、ネットワークには接続しない。

`data/.env` はコンテナ内のアプリ設定、ルートの `.env` はcompose変数に使われる。ルートの `.env` に `FIXED_PUBLIC_URL` を設定する。鍵は読取専用マウントし、Dockerイメージには含めない。

```text
docker compose up -d --build emergency-contact
```

公開ポートはホストの127.0.0.1に限定。cloudflaredはホスト上で実行し、接続先は `http://127.0.0.1:8000`。トンネル用Dockerネットワークのgatewayは172.30.80.1に固定し、標準でこのIPからの転送情報だけを信頼する。
Docker Desktopでは転送元が異なる場合があるため、実際の接続元を確認して `FORWARDED_ALLOW_IPS` にそのIPだけを設定する。HTTPSでアクセスしても転送を繰り返す場合は転送元IPと `X-Forwarded-Proto` を確認する。`*` で全接続元を信頼する設定にはしない。
同じmini PCからのlocalhost HTTP接続には、別設定の `LOCAL_HTTP_PEERS`（標準172.30.80.1）を使用する。Dockerのbridge経由をループバック接続として扱うための設定で、公開ホスト名へのHTTP接続やCloudflare等の転送ヘッダーが付いたHTTP接続は引き続きHTTPSへ誘導する。
ネットワーク172.30.80.0/24が既存のネットワークと重複する場合は、composeのsubnet・gatewayと信頼IPを一緒に変更する。

2026-10-22の整合性修正ではMac上のDockerを起動し、隔離したテスト用データで移行・鍵のマウント・起動・ヘルスチェック・バックアップ・復元を確認。Windows mini PC実機での更新後の確認は別途行う。

## バックアップ・復元

アプリ稼働中でもDBバックアップはSQLiteのbackup APIで整合性のある暗号化DBとして作る。ファイルの単純コピーはWAL内の更新を取りこぼす場合がある。

```text
python scripts/secure_storage.py backup --target backups/emergency-20261022.db
python scripts/secure_storage.py verify --source backups/emergency-20261022.db
```

このコマンドは手動実行。日次CSVは名簿・応答の出力であり、掲示板・設定・全プラグインを含む完全なバックアップではない。完全DBバックアップの定期実行はOSのタスク機能等で設定する。アップロード資料、`.env`、VAPID鍵、Cloudflare設定も別途保全する。

復元は別ファイルに行い、既存DBを上書きしない。

```text
python scripts/secure_storage.py restore --source backups/emergency-20261022.db --target restored/emergency.db
```

元と同じ `DB_KEY_FILE` が必要。復元後、アプリ停止中に `.env` の `DB_PATH` を復元先へ変更し、再起動して確認。Dockerではコンテナの停止後、対象ファイルをcompose指定の保存先へ配置する。

暗号化CSVの復元：

```text
python scripts/secure_storage.py decrypt-csv --source auto_exports/members_日時.csv.enc --target recovered-members.csv
```

復元したCSVは平文の個人情報。使用後の保管先・削除を管理する。

## 移行後に残る作業

- 元の `emergency.db`、旧バックアップDB、既存の平文CSVは、復元確認後に保管方針を決め、暗号化保管または不要分を削除。暗号化済みファイルを作っただけでは過去のコピーは保護されない。
- 鍵の複製を別保管し、担当者不在時にも復旧できる手順を用意。PCの再起動時に追加入力は不要だが、鍵ファイルが必要。
- 鍵が失われると復旧できない。新しい鍵を作っても以前のDBは開けない。鍵変更は新しいDBへの暗号化エクスポートとバックアップの扱いを含めて行う。
- GitHubの過去の履歴に残る旧DBと、公開済みの登録用合言葉を確認し、合言葉は運用側で変更する。履歴からの削除や公開設定変更はこの作業では行っていない。
- CloudflareのHTTP→HTTPS転送設定も確認。インターネットルーターの8000番ポートの転送は不要なので閉じる。
- ディスク暗号化は今回未実施。

## 参考

- [SQLCipher公式API・移行方法](https://www.zetetic.net/sqlcipher/sqlcipher-api/)
- [sqlcipher3配布元](https://pypi.org/project/sqlcipher3/)
- [Uvicornのプロキシ設定](https://uvicorn.dev/deployment/)
- [Cloudflareのオリジン接続](https://developers.cloudflare.com/tunnel/troubleshooting/https-origins/)
