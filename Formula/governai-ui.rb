class GovernaiUi < Formula
  desc "GovernAI workflow builder CLI/TUI"
  homepage "https://github.com/rrrozhd/governai-ui"
  url "https://files.pythonhosted.org/packages/source/g/governai-ui/governai_ui-0.1.0.tar.gz"
  sha256 "117778f2c1d2d8445a4447e89176f1ce13417fe404e36165b87ce44bb1e114bb"

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
