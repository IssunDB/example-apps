{
  description = "Example applications built with IssunDB";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system:
          let
            pkgs = import nixpkgs { inherit system; };
          in
          f pkgs
        );
    in
    {
      devShells = forAllSystems (pkgs:
        {
          default = pkgs.mkShell {
            name = "example-apps-dev";

            packages = with pkgs; [
              python313
              uv
              gnumake
              cargo
              rustc
              cmake
              gcc
              pkg-config
            ];

            shellHook = ''
              echo "IssunDB Example Apps development environment"
              echo "Python: $(python3 --version 2>/dev/null || echo 'not found')"
              echo "uv: $(uv --version 2>/dev/null || echo 'not found')"
              echo "cargo: $(cargo --version 2>/dev/null || echo 'not found')"
              echo "cmake: $(cmake --version 2>/dev/null || echo 'not found')"
            '';
          };
        });

      formatter = forAllSystems (pkgs: pkgs.nixpkgs-fmt);
    };
}
