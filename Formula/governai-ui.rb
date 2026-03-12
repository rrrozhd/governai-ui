class GovernaiUi < Formula
  desc "GovernAI workflow builder CLI/TUI"
  homepage "https://github.com/<org>/<repo>"
  url "https://files.pythonhosted.org/packages/source/g/governai-ui/governai_ui-0.1.0.tar.gz"
  sha256 "fad51f39ccb28b6f5f5a55c2bfb4354c31f27db172af4e3a858d50ac58dd60a8"

  depends_on "python@3.12"

  def install
    venv = libexec/"venv"
    system "python3.12", "-m", "venv", venv
    system venv/"bin/pip", "install", "--upgrade", "pip", "setuptools", "wheel"
    system venv/"bin/pip", "install", buildpath
    bin.install_symlink venv/"bin/governai-ui"
  end

  test do
    assert_match "usage", shell_output("#{bin}/governai-ui --help")
  end
end
