class GovernaiUi < Formula
  desc "GovernAI workflow builder CLI/TUI"
  homepage "https://github.com/rrrozhd/governai-ui"
  url "https://files.pythonhosted.org/packages/source/g/governai-ui/governai_ui-0.1.1.tar.gz"
  sha256 "34412dda480af5bd954088830e0564646691d9037644d9f7e19413f1dd93c9fc"

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
