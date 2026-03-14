class GovernaiUi < Formula
  desc "GovernAI workflow builder CLI/TUI"
  homepage "https://github.com/rrrozhd/governai-ui"
  url "https://files.pythonhosted.org/packages/source/g/governai-ui/governai_ui-0.1.0.tar.gz"
  sha256 "4f2371eb56c1d3b65f4f615454288192bbe4445d011cc2b17d8148b838dcb78d"

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
