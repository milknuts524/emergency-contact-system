# 復旧済みmini PCへ適用する整合性修正

対象はSQLCipherへの移行・復旧が終わり、公開サイトが正常な環境です。
この更新ではDBの再移行、鍵の再生成、既存DBの上書きは行いません。

## 修正内容

- Docker本体と移行ツールは同じsecretsフォルダーを使い、コンテナ内の鍵パスを `/run/secrets/database.key` に統一。
- 鍵の名前がディレクトリになった場合、既存ファイルを消さずに原因を表示。
- DBがない・空・別のシステムのDBなら、空の職員名簿を作らず起動を停止。
- 暗号化DBが既にあるのに鍵がない場合、再移行で無関係な鍵を生成しない。
- DBと鍵の組み合わせは読み取り専用で確認。Dockerの正常性確認にも使用。
- Dockerの依存関係を検証済みのバージョンへ固定。httpx2は別のテスト環境だけに導入。

## 適用順序

1. 現在のシステムフォルダーに、修正ZIPの中身を上書きコピー。`data`、`secrets`、`.env`は含まれず、変更しません。独自にcompose.ymlを変更している場合、その変更を残して差分を反映してください。
2. そのフォルダーでPowerShellを開き、事前確認を実行。稼働中のアプリはまだ停止しません。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_storage.ps1
```

3. `Storage verified.` が表示された場合だけ再ビルド・再作成。

```powershell
docker compose up -d --build emergency-contact
docker compose ps
```

4. `healthy` と表示され、いつもの公開HTTPS URLで既存の名簿・回答を確認できれば完了。

事前確認で失敗した場合は再作成せず、現在稼働しているコンテナを残して原因を確認してください。
`secrets/database.key` がフォルダーでも自動削除・自動生成はしません。既存暗号化DBに対応する元の鍵を復元します。
DBの再移行コマンドは実行しないでください。復旧後に追加された回答は旧平文DBには入っていません。

## 検証

通常DB・暗号化DB双方の回帰テストと、隔離したDockerの実際のマウント・移行・ヘルスチェック・バックアップ・復元を確認。
mini PC実機への適用は別作業。実データと鍵の照合には、上記の事前確認を使います。

Docker外のテスト環境は `python -m pip install -r requirements-test.txt` で準備。
Docker統合テストはイメージ `emergency-contact-storage-fix:test` をビルド後、`RUN_DOCKER_TESTS=1` を設定して `tests/test_docker_storage.py` を実行。
