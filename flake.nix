{
  description = "Noctalia Minimizer: reversible window minimization for Niri (Noctalia Shell plugin)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      version = import ./nix/version.nix;
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        noctalia-minimizer = pkgs.callPackage ./nix/package.nix { inherit version; };
        default = noctalia-minimizer;
      });

      apps = forAllSystems (pkgs: let pkg = self.packages.${pkgs.stdenv.hostPlatform.system}.default; in {
        default = { type = "app"; program = "${pkg}/bin/noctalia-minimizer"; meta.description = "Minimize/restore CLI"; };
        setup = { type = "app"; program = "${pkg}/bin/noctalia-minimizer-setup"; meta.description = "Per-user Noctalia/Niri setup"; };
      });

      overlays.default = final: _prev: {
        noctalia-minimizer = final.callPackage ./nix/package.nix { inherit version; };
      };

      nixosModules.default = import ./nix/module.nix;
      nixosModules.noctalia-minimizer = self.nixosModules.default;

      checks = forAllSystems (pkgs: import ./nix/checks.nix { inherit pkgs self nixpkgs; });

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
