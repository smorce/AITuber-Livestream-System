<!-- 初回 -->
cd llma.cpp.20260225_204122

<!-- 画像インプットver -->  
<!-- ローカルモデルから読み込む -->
./build/bin/llama-server \
    --model ./unsloth/Qwen3.5-35B-A3B-GGUF/unsloth_Qwen3.5-35B-A3B-GGUF_Qwen3.5-35B-A3B-UD-MXFP4_MOE.gguf \
    --mmproj ./unsloth/Qwen3.5-35B-A3B-GGUF/mmproj-F16.gguf \
    --alias "Qwen3.5-35B-A3B-GGUF-UD-MXFP4_MOE" \
    --ctx-size 12800 \
    --temp 0.7 \
    --top-p 0.8 \
    --top-k 20 \
    --min-p 0.00 \
    --chat-template-kwargs "{\"enable_thinking\": false}" \
    --cache-type-k q4_0 \
    --cache-type-v q4_0 \
    --threads 16 --prio 2 \
    -ngl 10 \
    -np 2 \
    --flash-attn on \
    --jinja \
    --no-mmap \
    --port 1067 \
    --host 0.0.0.0


ngl 10 にしたらできた。

接続先：`http://127.0.0.1:1067/v1`
モデル：`Qwen3.5-35B-A3B-GGUF-UD-MXFP4_MOE`
応答：`接続確認できました。`（正常終了）
LLM稼働中の空きVRAM：約14.1GiB

とりあえず、これでやってみる。