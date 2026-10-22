# Docker Desktopで動いているmini PCの移行

Windowsのmini PCを想定。Docker DesktopとCloudflareの電源投入時の自動起動は変更しません。
この作業中だけサービスを停止します。復旧できる担当者がいる時間帯に行ってください。

## 1. 作業フォルダーを開く

エクスプローラーで、現在のシステムの `compose.yml` と `data` フォルダーがある場所を開きます。
`data` の中に `emergency.db` があることを確認してください。
見つからない場合は進めず、現在のDB保存先を確認します。

エクスプローラー上部のアドレス欄へ `powershell` と入力し、Enter。
青色または黒色の入力画面が開きます。以下のコマンドは、その画面へ1つずつ貼り付けてEnterで実行します。

## 2. 旧システムを停止して、元のフォルダーをコピー

```powershell
docker compose down
```

停止後、エクスプローラーでシステムのフォルダー全体を別の場所へコピーして保存。
コピー先は作業フォルダーの中ではなく、隣のフォルダーや外付け媒体にします。
このコピーには平文の個人情報と設定が含まれるため、公開・共有しないでください。
`docker compose down` に `-v` は付けません。

## 3. 更新ファイルをコピー

Docker移行対応の新しいZIPを展開し、中のファイルとフォルダーを「元の作業フォルダー」へコピー。
同じ名前のファイルは置き換えます。移行先を別の新しいフォルダーにしないでください。

ZIPには既存の `data`・`.env`・`secrets`・資料ファイルは含まれません。これらは削除・置換しないでください。
元の作業フォルダー内に `storage_tools.py` と新しい `compose.yml` があることを確認します。

## 4. DockerでDBを暗号化

手順1で開いたPowerShellで実行します。

```powershell
docker compose run --rm --build storage-tools migrate --source /app/data/emergency.db --target /app/data/emergency.encrypted.db
```

初回はイメージのダウンロードと作成に時間がかかります。Pythonをmini PCへ追加する必要はありません。

次の表示が出れば成功です。

```text
Encrypted database created and verified. Original plaintext file was retained.
```

成功後、元の `data/emergency.db` はそのまま残り、次の2ファイルが増えます。

- `data/emergency.encrypted.db`：暗号化されたDB
- `secrets/database.key`：DBを開く鍵

エラーが出たら、その先へ進めず、エラー表示を確認してください。特に「既にファイルがある」という場合は、DBや鍵を消してやり直さないでください。

## 5. 暗号鍵を別保管

`secrets/database.key` をUSBなどの別保管先へコピーします。
鍵の中身をチャット・メール・GitHubへ貼り付ける必要はありません。
鍵が失われると暗号化DBから復旧できません。DBバックアップと鍵は別管理にしてください。

## 6. 新システムを起動

```powershell
docker compose up -d --build emergency-contact
```

起動状態を確認します。

```powershell
docker compose ps
```

`emergency-contact-system` が `Up` と表示されれば起動しています。
`Restarting` や `Exited` の場合は、次のコマンドで原因を確認します。

```powershell
docker compose logs --tail 50 emergency-contact
```

`restart: unless-stopped` は維持しているので、コンテナが正常に起動した後は、従来どおりDocker Desktopが立ち上がるとアプリも起動します。

## 7. スマホで確認

いつもの `https://emergency.tohyama.cc` からアクセスし、登録者・安否情報・資料が残っていること、管理画面と通知を確認。
Cloudflareの既存の自動起動は変更しません。同じmini PC上でCloudflareが起動する構成が前提です。

公開URLが転送を繰り返す場合は、Docker Desktopからアプリへ接続するときの転送元IPの調整が必要です。`FORWARDED_ALLOW_IPS=*` として回避せず、ログを確認してください。
公開URLで接続できない場合は、Cloudflareの接続先が同じmini PCの `http://127.0.0.1:8000` になっているかを確認します。
別のPCからmini PCのIPアドレスと8000番ポートへ直接接続する方法は、今回の変更後は使えません。
同じmini PCの `http://localhost:8000` は利用できます。Dockerのbridge gatewayからの保守接続を `LOCAL_HTTP_PEERS` に指定しています。Docker Desktopで実際の接続元IPが異なる場合は、そのIPを確認して設定を調整します。

## 8. バックアップと電源投入後の確認

暗号化DBのバックアップを作ります。

```powershell
docker compose run --rm storage-tools backup --target /app/data/emergency.encrypted.backup-20261022.db
```

このバックアップファイルは `data` フォルダーにできます。外付け媒体などにも保管し、同じ名前で再実行しないでください。
移行直後の元DBには、その後の入力は反映されません。

mini PCを再起動し、いつものHTTPS URLから再び利用できることを確認してください。
動作確認と鍵の別保管が終わるまでは元DBと手順2のコピーを消しません。確認後、残した平文データの保管・削除を決めます。

## 戻す必要がある場合

新システムを `docker compose down` で停止し、手順2でコピーした旧フォルダーで `docker compose up -d` を実行。
移行後の入力は旧DBに入っていないため、新版へ入力した内容がある場合は、旧版へ戻す前に対応を相談してください。
