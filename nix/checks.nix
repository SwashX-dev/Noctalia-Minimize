{ pkgs, self, nixpkgs }:
let
  system = pkgs.stdenv.hostPlatform.system;
  pkg = self.packages.${system}.default;
  plugin = "${pkg}/share/noctalia-minimizer/plugins/minimizer";
  # A minimal NixOS configuration that only enables this module.
  nixos = nixpkgs.lib.nixosSystem {
    inherit system;
    modules = [
      self.nixosModules.default
      {
        boot.isContainer = true;
        system.stateVersion = "26.05";
        programs.noctalia-minimizer.enable = true;
        programs.noctalia-minimizer.keybindings.restoreAll = "Mod+Ctrl+M";
      }
    ];
  };
  etcBinds = nixos.config.environment.etc."noctalia-minimizer/niri-binds.kdl".source;
in
{
  # Builds the package; its checkPhase runs the Python unit tests.
  package = pkg;

  # Luau syntax, the Noctalia manifest linter, and placeholder substitution.
  plugin = pkgs.runCommand "noctalia-minimizer-plugin-check" { nativeBuildInputs = [ pkgs.luau pkgs.noctalia ]; } ''
    export HOME=$TMPDIR
    for f in ${plugin}/*.luau; do luau-compile --null "$f" > /dev/null; done
    noctalia plugins lint ${plugin} | tee lint.txt
    grep -q "0 errors" lint.txt
    grep -q '"${pkg}/bin/noctalia-minimizer"' ${plugin}/client.luau
    ! grep -rq '@backend@' ${plugin}
    touch $out
  '';

  # Both the shipped and the module-generated bindings parse as Niri config.
  niri-binds = pkgs.runCommand "noctalia-minimizer-niri-check" { nativeBuildInputs = [ pkgs.niri pkgs.python3 ]; } ''
    export HOME=$TMPDIR XDG_RUNTIME_DIR=$TMPDIR
    for f in ${pkg}/share/noctalia-minimizer/niri-binds.kdl ${etcBinds}; do
      printf 'include "%s"\n' "$f" > config.kdl
      niri validate -c config.kdl
    done
    grep -q 'Mod+Ctrl+M' ${etcBinds}
    touch $out
  '';

  # The module installs the plugin into the system profile and nothing else.
  module = pkgs.runCommand "noctalia-minimizer-module-check" { } ''
    test -f ${nixos.config.system.path}/share/noctalia-minimizer/plugins/minimizer/plugin.toml
    test -x ${nixos.config.system.path}/bin/noctalia-minimizer
    test -x ${nixos.config.system.path}/bin/noctalia-minimizer-setup
    touch $out
  '';
}
// pkgs.lib.optionalAttrs (system == "x86_64-linux") {
  # Boots a VM with the module and exercises the installed CLI end to end
  # (no compositor in the VM, so it must fail safely and report why).
  vm = pkgs.testers.runNixOSTest {
    name = "noctalia-minimizer-vm";
    nodes.machine = { ... }: {
      imports = [ self.nixosModules.default ];
      programs.noctalia-minimizer.enable = true;
      users.users.alice = { isNormalUser = true; };
    };
    testScript = ''
      machine.wait_for_unit("multi-user.target")
      machine.succeed("test -f /run/current-system/sw/share/noctalia-minimizer/plugins/minimizer/plugin.toml")
      machine.succeed("grep -q 'Mod+Shift+M' /etc/noctalia-minimizer/niri-binds.kdl")
      out = machine.fail("su - alice -c 'noctalia-minimizer status'")
      assert "Niri" in out, out
      machine.succeed("su - alice -c 'mkdir -p ~/.config/niri && printf \"binds {\\n}\\n\" > ~/.config/niri/config.kdl'")
      machine.succeed("su - alice -c 'noctalia-minimizer-setup apply --no-noctalia'")
      machine.succeed("su - alice -c 'grep -q /etc/noctalia-minimizer/niri-binds.kdl ~/.config/niri/config.kdl'")
      machine.succeed("su - alice -c 'noctalia-minimizer-setup undo --keep-plugin'")
      machine.fail("su - alice -c 'grep -q noctalia-minimizer ~/.config/niri/config.kdl'")
    '';
  };
}
