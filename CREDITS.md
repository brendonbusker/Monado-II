# Credits

- **TheMonadoGuy / Monado contributors — original Monado.** This is a continuation
  of that project, not a claim to have created its original recompiler/runtime.
  Historical upstream: <https://github.com/TheMonadoGuy/Monado> (unavailable when
  checked November 7, 2026). The creator's
  [original announcement](https://www.reddit.com/r/decomps/comments/1xfdgiz/monado_a_xenoblade_de_recomp_support_not_provided/)
  identifies that repository and invites continuation. The inherited source
  snapshot did not contain upstream Git history; its MIT notices are preserved.
- **Peiikai — [LASRecomp](https://github.com/peiikai/LASRecomp)**, MIT. Monado's
  AArch64-to-C lifter and substantial runtime derive from LASRecomp, recorded
  upstream revision `136f679`. Its original copyright notice remains intact.
- **Monado II contributors** — native Linux integration, timing/menu/footstep
  corrections, diagnostics/testing, source publication tooling and ongoing work.
- **patrickksmdev — AMD/RADV testing.** Isolated the RX 7600 colorful-dot
  workaround by testing `nodcc` and lean formats separately, and reported the
  visual result and performance observations used for the compatibility change.
- **Launcher illustration** — generated with OpenAI image generation under the
  maintainer's direction. The exact restored asset is documented in
  [artwork provenance](Monado_Linux/tools/launcher/assets/ARTWORK_PROVENANCE.md).
  This is not an exclusive copyright claim over generated imagery or an
  endorsement by OpenAI, Nintendo or Monolith Soft.
- **Dependency authors** — Dear ImGui, SMAA, AMD FidelityFX, NVIDIA Streamline/NGX,
  DejaVu, SDL, Vulkan tooling, LLVM/Zig, FFmpeg, Opus and other components retain
  their own credit and licenses. See [NOTICE](NOTICE.md).
- **AppImage contributors** — the optional local launcher image uses the pinned
  [AppImage type2 runtime](https://github.com/AppImage/type2-runtime). Its notices
  and statically linked dependency licenses accompany the local image; no runtime
  binary is committed in this source repository.

The original Monado documentation states that it used extensive Claude/Claude
Code assistance under human direction. Monado II also uses AI-assisted development
and human testing. No involvement or endorsement by Nintendo, Monolith Soft or
the original contributors is implied.
