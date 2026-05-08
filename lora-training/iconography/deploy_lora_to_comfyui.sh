#!/usr/bin/env bash
# Promote a trained iconography LoRA checkpoint into the lab's
# ComfyUI loras dir.
#
# The lab has /zpool/models/comfyui shared via NFS to all consuming
# CTs (gigabyte, desktop, laptop) — see ai-lab/CLAUDE.md "Centralized
# Model Storage". Promoting a LoRA there makes it immediately
# available to:
#   - Desktop CT 111 (cartography ComfyUI on RTX 3090)
#   - Any future CT that mounts /mnt/models/comfyui
#
# Usage:
#   ./deploy_lora_to_comfyui.sh                           # picks the latest ckpt
#   ./deploy_lora_to_comfyui.sh 1500                      # picks step 1500
#   ./deploy_lora_to_comfyui.sh wh40k_iconography_..safe  # explicit filename

set -euo pipefail

GIGABYTE_HOST="${GIGABYTE_HOST:-192.168.9.5}"
TRAINER_HOST="${TRAINER_HOST:-198.51.100.30}"
SSHPASS_VAR="${SSHPASS_VAR:-Whitey911jamie!}"

CKPT_DIR_REMOTE="/opt/lora-training/outputs/wh40k_iconography"
COMFYUI_LORAS_HOST_PATH="/zpool/models/comfyui/loras"

# ── Pick checkpoint ──────────────────────────────────────────────────
arg="${1:-}"
SSHPASS="$SSHPASS_VAR" sshpass -e ssh -o StrictHostKeyChecking=accept-new \
    root@"$TRAINER_HOST" "ls $CKPT_DIR_REMOTE/wh40k_iconography_*.safetensors" >/tmp/_ckpts.list
if [[ -z "$arg" ]]; then
    CKPT=$(tail -1 /tmp/_ckpts.list)
    echo "[deploy] no arg — picking latest: $(basename "$CKPT")"
elif [[ "$arg" =~ ^[0-9]+$ ]]; then
    CKPT=$(grep -E "_0*${arg}\.safetensors$" /tmp/_ckpts.list || true)
    [[ -n "$CKPT" ]] || { echo "no ckpt matches step $arg"; cat /tmp/_ckpts.list; exit 2; }
elif [[ "$arg" == *.safetensors ]]; then
    CKPT="$CKPT_DIR_REMOTE/$arg"
else
    echo "usage: $0 [step|filename.safetensors]"; exit 2
fi

# ── Promote: rsync from trainer CT to gigabyte host's
#    /zpool/models/comfyui/loras (the NFS-served comfyui models dir).
#    Both endpoints live on the same physical host but cross-CT, so we
#    copy via the gigabyte host directly, not via the laptop.
TARGET="${COMFYUI_LORAS_HOST_PATH}/wh40k_iconography.safetensors"
echo "[deploy] copying $(basename "$CKPT") -> ${GIGABYTE_HOST}:$TARGET"

# Step 1: pull from CT 140 to a tmp file on the gigabyte host
SSHPASS="$SSHPASS_VAR" sshpass -e ssh root@"$GIGABYTE_HOST" "
    mkdir -p '$COMFYUI_LORAS_HOST_PATH'
    pct pull 140 '$CKPT' '/tmp/wh40k_iconography.safetensors.tmp'
    mv '/tmp/wh40k_iconography.safetensors.tmp' '$TARGET'
    chmod 644 '$TARGET'
    echo '[gigabyte] now at:'
    ls -lh '$TARGET'
"

# Symlink an immutable timestamped copy so prior versions are kept
SSHPASS="$SSHPASS_VAR" sshpass -e ssh root@"$GIGABYTE_HOST" "
    cp -al '$TARGET' '${COMFYUI_LORAS_HOST_PATH}/wh40k_iconography.\$(date +%Y%m%d-%H%M%S).safetensors' 2>/dev/null \
        || cp '$TARGET' '${COMFYUI_LORAS_HOST_PATH}/wh40k_iconography.\$(date +%Y%m%d-%H%M%S).safetensors'
    ls -lh '${COMFYUI_LORAS_HOST_PATH}/' | grep wh40k_iconography
"

echo
echo "Done. The LoRA is now live in /zpool/models/comfyui/loras/ which"
echo "is NFS-mounted at /mnt/models/comfyui/loras on all consumer CTs."
echo
echo "In ComfyUI workflows, reference it with:"
echo "  <lora:wh40k_iconography:0.8>, sym_aquila on the chapel apse, ..."
echo
echo "Trigger tokens:"
echo "  sym_aquila, sym_inq_rosette, sym_mech_cog, sym_militarum_winged_skull,"
echo "  sym_sororitas_lys, sym_ministorum, sym_administratum, sym_arbites,"
echo "  sym_telepathica_eye, sym_imperial_navy, sym_rogue_trader"
