"""Vista previa local de formatos Telegram (sin MT5). Ejecutar: python preview_tg_messages.py"""

from __future__ import annotations

import os
import sys

# Asegurar cwd importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    os.environ["TELEGRAM_TZ_LABEL"] = "UTC-03:00"
    os.environ["SIGNALS_ONLY"] = "1"

    from mt5_prices import _telegram_signal_message_text

    def block(title: str, style: str, signal: str, **kwargs) -> None:
        os.environ["TELEGRAM_STYLE"] = style
        bid = kwargs.get("bid", 2650.25)
        ask = kwargs.get("ask", 2650.48)
        atr = kwargs.get("atr", 12.45)
        print("=" * 58)
        print(title)
        print("=" * 58)
        print(
            _telegram_signal_message_text(
                kwargs.get("symbol", "XAUUSD"),
                signal,
                bid,
                ask,
                kwargs.get("fast", 2652.3),
                kwargs.get("slow", 2648.1),
                "M5",
                "M15",
                extra_footer=kwargs.get("footer"),
                atr_val=atr,
                atr_period=14,
                sl_atr_mult=1.5,
                rr=2.5,
                trend_detail=kwargs.get(
                    "td", "M15 alineado alcista para el filtro (ejemplo)."
                ),
            )
        )
        print()

    block("Estilo VIP — COMPRA (BUY)", "vip", "BUY")
    block("Estilo VIP — VENTA (SELL)", "vip", "SELL", bid=2649.90, ask=2650.12)
    block("Estilo VIP — HOLD", "vip", "HOLD", atr=None)

    os.environ["TELEGRAM_STYLE"] = "rich"
    os.environ["TELEGRAM_DEEP_ANALYSIS"] = "0"
    print("=" * 58)
    print("Estilo RICH — extracto (sin análisis profundo TELEGRAM_DEEP_ANALYSIS)")
    print("=" * 58)
    msg = _telegram_signal_message_text(
        "XAUUSD",
        "BUY",
        2650.25,
        2650.48,
        2652.3,
        2648.1,
        "M5",
        "M15",
        atr_val=12.45,
        atr_period=14,
        trend_detail="M15 alineado alcista para el filtro (ejemplo).",
    )
    lines = msg.splitlines()
    for line in lines[:32]:
        print(line)
    if len(lines) > 32:
        print("...")
        print(f"(total {len(lines)} líneas; con DEEP_ANALYSIS=1 se suma mucho más texto)")

    out_path = os.path.join(os.path.dirname(__file__), "preview_tg_output.txt")
    # Copia UTF-8 por si la consola no muestra emojis
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("Ver también este archivo si la consola corta símbolos.\n\n")
        os.environ["TELEGRAM_STYLE"] = "vip"
        for sig, title in [
            ("BUY", "VIP BUY"),
            ("SELL", "VIP SELL"),
            ("HOLD", "VIP HOLD"),
        ]:
            f.write("=" * 58 + "\n" + title + "\n" + "=" * 58 + "\n")
            f.write(
                _telegram_signal_message_text(
                    "XAUUSD",
                    sig,
                    2650.25,
                    2650.48,
                    2652.3,
                    2648.1,
                    "M5",
                    "M15",
                    atr_val=12.45 if sig != "HOLD" else None,
                    atr_period=14,
                    trend_detail="M15 ejemplo.",
                )
                + "\n\n"
            )
    print(f"\n[Guardado también en: {out_path}]")


if __name__ == "__main__":
    main()
