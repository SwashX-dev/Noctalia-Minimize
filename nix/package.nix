{ lib, stdenvNoCC, python3, makeWrapper, version ? (import ./version.nix) }:
stdenvNoCC.mkDerivation {
  pname = "noctalia-minimizer";
  inherit version;
  src = lib.fileset.toSource {
    root = ./..;
    fileset = lib.fileset.unions [ ../backend ../plugin ../niri ../tests ../README.md ../LICENSE ../CHANGELOG.md ];
  };
  nativeBuildInputs = [ makeWrapper ];
  nativeCheckInputs = [ python3 ];
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    PYTHONPATH=$PWD/backend PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    share=$out/share/noctalia-minimizer
    mkdir -p $out/bin $out/libexec/noctalia-minimizer $share/plugins/minimizer $out/share/doc/noctalia-minimizer
    cp backend/*.py $out/libexec/noctalia-minimizer/
    cp -r plugin/. $share/plugins/minimizer/
    substituteInPlace $share/plugins/minimizer/client.luau \
      --replace-fail '"@backend@"' "\"$out/bin/noctalia-minimizer\""
    cp niri/binds.kdl $share/niri-binds.kdl
    # -s: ignore the user site directory; the backend uses only the standard library.
    makeWrapper ${python3}/bin/python3 $out/bin/noctalia-minimizer \
      --add-flags "-s $out/libexec/noctalia-minimizer/cli.py"
    makeWrapper ${python3}/bin/python3 $out/bin/noctalia-minimizer-setup \
      --add-flags "-s $out/libexec/noctalia-minimizer/setup.py" \
      --set-default NOCTALIA_MINIMIZER_SHARE "$share"
    cp README.md LICENSE CHANGELOG.md $out/share/doc/noctalia-minimizer/
    runHook postInstall
  '';
  meta = {
    description = "Reversible window minimization for Niri as a native Noctalia Shell plugin";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "noctalia-minimizer";
  };
}
