#!/bin/bash
# 3.9.1: a room sound's loop from a recording (due_crew/sounds/CREDITS.md
# has each one's source and numbers), e.g.
#   tools/cut_sound.sh ffmpeg 525046_10637780-hq.ogg rain 36 60 3 -23.3
# writes rain.ogg in the current folder. Any ffmpeg 7 with libopus will do.
# cut_sound.sh <ffmpeg> <src> <name> <start> <length> <crossfade> <target LUFS>
# A seamless loop: the X seconds after the loop's end crossfade (equal power)
# into its first X seconds, so its end runs straight into its start. Trimmed
# by decoding (atrim), never by seeking; levelled to the target, then a limiter
# keeps the peaks a dB under full scale.
FF=$1; SRC=$2; NAME=$3; ST=$4; L=$5; X=$6; T=$7
TAIL=$(python3 -c "print($ST+$L)")
B=$(python3 -c "print($ST+$X)"); M=$(python3 -c "print($L-$X)")
$FF -v warning -y -i $SRC -filter_complex \
 "[0:a]aresample=48000,asplit=3[t][h][m];[t]atrim=start=$TAIL:duration=$X,asetpts=PTS-STARTPTS,afade=t=out:d=$X:curve=qsin[tf];[h]atrim=start=$ST:duration=$X,asetpts=PTS-STARTPTS,afade=t=in:d=$X:curve=qsin[hf];[tf][hf]amix=inputs=2:normalize=0:duration=longest[x];[m]atrim=start=$B:duration=$M,asetpts=PTS-STARTPTS[mb];[x][mb]concat=n=2:v=0:a=1" \
 -c:a pcm_f32le $NAME.loop.wav
I=$($FF -hide_banner -nostats -i $NAME.loop.wav -af ebur128 -f null - 2>&1 | grep -E "^\s+I:" | tail -1 | awk '{print $2}')
G=$(python3 -c "print(round($T - ($I), 2))")
$FF -v error -y -i $NAME.loop.wav -af "volume=${G}dB,alimiter=limit=0.89:attack=2:release=60:level=disabled:latency=1" -c:a libopus -b:a 80k -vbr on -application audio $NAME.ogg
printf "%-6s loop %s s from %s s (crossfade %s s), was %s LUFS, +%s dB -> " $NAME $L $ST $X $I $G
$FF -hide_banner -nostats -i $NAME.ogg -af ebur128=peak=true -f null - 2>&1 | grep -E "^\s+(I|Peak):" | tail -2 | tr -s ' ' | tr '\n' ' '; echo
